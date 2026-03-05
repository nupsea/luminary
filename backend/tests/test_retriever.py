"""Tests for HybridRetriever — keyword, vector, and RRF merge."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from stubs import MockEmbeddingService as _MockEmbeddingService

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel
from app.services.retriever import HybridRetriever
from app.types import ScoredChunk
from app.workflows.ingestion import IngestionState, keyword_index_node

# ---------------------------------------------------------------------------
# Shared fixture — in-memory SQLite with FTS5
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    """Wire an in-memory SQLite DB into the app's global singletons."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


async def _insert_doc_and_chunk(factory, tmp_path, doc_id: str, chunk_id: str, text_content: str):
    """Helper: insert a document and one chunk into the DB."""
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test Doc",
                format="txt",
                content_type="notes",
                word_count=10,
                page_count=1,
                file_path=str(tmp_path / "doc.txt"),
                stage="indexing",
            )
        )
        session.add(
            ChunkModel(
                id=chunk_id,
                document_id=doc_id,
                section_id=None,
                text=text_content,
                token_count=len(text_content.split()),
                page_number=0,
                speaker=None,
                chunk_index=0,
            )
        )
        await session.commit()


async def _populate_fts(engine, doc_id: str):
    """Helper: insert chunks into FTS5 for a given document."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO chunks_fts(rowid, text, chunk_id, document_id) "
                "SELECT rowid, text, id, document_id FROM chunks WHERE document_id = :doc_id"
            ),
            {"doc_id": doc_id},
        )


# ---------------------------------------------------------------------------
# rrf_merge unit tests (no I/O)
# ---------------------------------------------------------------------------


def test_rrf_merge_chunk_in_both_ranks_first():
    """A chunk found in both vector and keyword results should rank highest."""
    retriever = HybridRetriever()
    shared_id = "chunk_shared"

    vec_results = [
        ScoredChunk(shared_id, "doc1", "shared text", "", 0, 0.9, "vector"),
        ScoredChunk("chunk_v", "doc1", "vector only", "", 0, 0.7, "vector"),
    ]
    kw_results = [
        ScoredChunk(shared_id, "doc1", "shared text", "", 0, -1.0, "keyword"),
        ScoredChunk("chunk_k", "doc1", "keyword only", "", 0, -2.0, "keyword"),
    ]

    merged = retriever.rrf_merge(vec_results, kw_results, k=3)

    assert len(merged) == 3
    assert merged[0].chunk_id == shared_id
    assert merged[0].source == "both"


def test_rrf_merge_source_labels_correct():
    """Chunks only in one list get correct source label."""
    retriever = HybridRetriever()
    vec_results = [ScoredChunk("v1", "doc1", "text", "", 0, 0.9, "vector")]
    kw_results = [ScoredChunk("k1", "doc1", "text", "", 0, -1.0, "keyword")]

    merged = retriever.rrf_merge(vec_results, kw_results, k=5)
    sources = {m.chunk_id: m.source for m in merged}

    assert sources["v1"] == "vector"
    assert sources["k1"] == "keyword"


def test_rrf_merge_respects_k():
    """rrf_merge returns at most k results."""
    retriever = HybridRetriever()
    vec_results = [
        ScoredChunk(f"c{i}", "doc1", f"text {i}", "", 0, float(10 - i), "vector")
        for i in range(10)
    ]

    merged = retriever.rrf_merge(vec_results, [], k=4)
    assert len(merged) == 4


def test_rrf_merge_scores_are_positive():
    """All RRF scores should be positive (1/(60+rank) > 0)."""
    retriever = HybridRetriever()
    vec_results = [ScoredChunk(f"c{i}", "d", f"t{i}", "", 0, 0.5, "vector") for i in range(5)]
    kw_results = [ScoredChunk(f"c{i}", "d", f"t{i}", "", 0, -1.0, "keyword") for i in range(5)]

    merged = retriever.rrf_merge(vec_results, kw_results, k=5)
    assert all(m.score > 0 for m in merged)


def test_rrf_merge_empty_inputs():
    """rrf_merge with both inputs empty returns empty list."""
    retriever = HybridRetriever()
    assert retriever.rrf_merge([], [], k=10) == []


def test_rrf_merge_one_empty_list():
    """rrf_merge with one empty list still ranks the other correctly."""
    retriever = HybridRetriever()
    vec_results = [
        ScoredChunk("c1", "d", "text 1", "", 0, 0.9, "vector"),
        ScoredChunk("c2", "d", "text 2", "", 0, 0.8, "vector"),
    ]
    merged = retriever.rrf_merge(vec_results, [], k=2)
    assert len(merged) == 2
    # c1 has rank 1, c2 has rank 2 → c1 ranks first
    assert merged[0].chunk_id == "c1"
    assert merged[0].source == "vector"


# ---------------------------------------------------------------------------
# keyword_search integration tests
# ---------------------------------------------------------------------------


async def test_keyword_search_returns_matching_chunks(test_db):
    """keyword_search finds a chunk by its text content."""
    engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    await _insert_doc_and_chunk(factory, tmp_path, doc_id, chunk_id, "machine learning algorithms")
    await _populate_fts(engine, doc_id)

    retriever = HybridRetriever()
    results = await retriever.keyword_search("machine learning", None, k=5)

    assert len(results) >= 1
    assert results[0].chunk_id == chunk_id
    assert results[0].source == "keyword"
    assert results[0].document_id == doc_id


async def test_keyword_search_returns_empty_for_no_match(test_db):
    """keyword_search returns empty list when query matches nothing."""
    engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    await _insert_doc_and_chunk(factory, tmp_path, doc_id, chunk_id, "machine learning algorithms")
    await _populate_fts(engine, doc_id)

    retriever = HybridRetriever()
    results = await retriever.keyword_search("quantum entanglement", None, k=5)
    assert results == []


async def test_keyword_search_filters_by_document_id(test_db):
    """keyword_search only returns results for the given document_ids."""
    engine, factory, tmp_path = test_db
    doc_id_a = str(uuid.uuid4())
    doc_id_b = str(uuid.uuid4())
    chunk_a = str(uuid.uuid4())
    chunk_b = str(uuid.uuid4())

    await _insert_doc_and_chunk(factory, tmp_path, doc_id_a, chunk_a, "neural network training")
    await _insert_doc_and_chunk(factory, tmp_path, doc_id_b, chunk_b, "neural network inference")
    await _populate_fts(engine, doc_id_a)
    await _populate_fts(engine, doc_id_b)

    retriever = HybridRetriever()
    results = await retriever.keyword_search("neural network", [doc_id_a], k=10)

    returned_docs = {r.document_id for r in results}
    assert returned_docs == {doc_id_a}
    assert chunk_b not in {r.chunk_id for r in results}


# ---------------------------------------------------------------------------
# keyword_index_node integration test
# ---------------------------------------------------------------------------


async def test_keyword_index_node_populates_fts5(test_db):
    """keyword_index_node inserts chunks into FTS5 so they can be retrieved."""
    engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    await _insert_doc_and_chunk(factory, tmp_path, doc_id, chunk_id, "deep learning research")

    state: IngestionState = {
        "document_id": doc_id,
        "file_path": str(tmp_path / "doc.txt"),
        "format": "txt",
        "parsed_document": None,
        "content_type": "notes",
        "chunks": [{"id": chunk_id, "text": "deep learning research", "index": 0}],
        "status": "indexing",
        "error": None,
    }

    await keyword_index_node(state)

    # Verify via direct FTS5 query
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH 'deep' LIMIT 5"
            )
        )
        rows = result.fetchall()

    assert len(rows) >= 1
    assert any(row.chunk_id == chunk_id for row in rows)


# ---------------------------------------------------------------------------
# vector_search unit test (mocked LanceDB)
# ---------------------------------------------------------------------------


def test_vector_search_returns_scored_chunks(monkeypatch):
    """vector_search maps LanceDB rows to ScoredChunk with score=1-distance."""
    fake_row = {
        "chunk_id": "c1",
        "document_id": "d1",
        "text": "some text",
        "section_heading": "Intro",
        "page": 1,
        "_distance": 0.2,
    }

    mock_table = MagicMock()
    mock_search = MagicMock()
    mock_search.metric.return_value = mock_search
    mock_search.limit.return_value = mock_search
    mock_search.to_list.return_value = [fake_row]
    mock_table.search.return_value = mock_search

    mock_lancedb = MagicMock()
    mock_lancedb._get_table.return_value = mock_table

    mock_embedder = _MockEmbeddingService()

    with (
        patch("app.services.vector_store.get_lancedb_service", return_value=mock_lancedb),
        patch("app.services.embedder.get_embedding_service", return_value=mock_embedder),
    ):
        retriever = HybridRetriever()
        results = retriever.vector_search("test query", None, k=5)

    assert len(results) == 1
    assert results[0].chunk_id == "c1"
    assert results[0].source == "vector"
    assert abs(results[0].score - 0.8) < 1e-6  # 1.0 - 0.2


def test_vector_search_filters_by_document_id(monkeypatch):
    """vector_search passes a WHERE filter when document_ids is provided."""
    mock_table = MagicMock()
    mock_search = MagicMock()
    mock_search.metric.return_value = mock_search
    mock_search.limit.return_value = mock_search
    mock_search.where.return_value = mock_search
    mock_search.to_list.return_value = []
    mock_table.search.return_value = mock_search

    mock_lancedb = MagicMock()
    mock_lancedb._get_table.return_value = mock_table

    mock_embedder = _MockEmbeddingService()

    with (
        patch("app.services.vector_store.get_lancedb_service", return_value=mock_lancedb),
        patch("app.services.embedder.get_embedding_service", return_value=mock_embedder),
    ):
        retriever = HybridRetriever()
        retriever.vector_search("query", ["doc_abc"], k=5)

    mock_search.where.assert_called_once()
    where_arg = mock_search.where.call_args[0][0]
    assert "doc_abc" in where_arg


# ---------------------------------------------------------------------------
# _diversify unit tests
# ---------------------------------------------------------------------------


def test_diversify_no_op_when_already_diverse():
    """_diversify returns top-k unchanged when candidates span many sections."""
    from app.services.retriever import _diversify

    chunks = [
        ScoredChunk(f"c{i}", "d", f"t{i}", f"Section {i}", 0, 1.0 - i * 0.1, "vector")
        for i in range(10)
    ]
    # 10 different headings → concentration = 0.1 ≤ 0.6 → no reorder
    result = _diversify(chunks, k=5)
    assert len(result) == 5
    assert result[0].chunk_id == "c0"


def test_diversify_round_robin_when_clustered():
    """_diversify reorders when >60% of top-k chunks share the same section."""
    from app.services.retriever import _diversify

    chunks = [
        ScoredChunk(f"a{i}", "d", f"text a{i}", "Chapter 18", 0, 1.0 - i * 0.05, "vector")
        for i in range(8)
    ] + [
        ScoredChunk(f"b{i}", "d", f"text b{i}", "Chapter 1", 0, 0.3 - i * 0.05, "vector")
        for i in range(2)
    ]
    # Without diversity, top-5 are all Chapter 18 (concentration = 1.0)
    result = _diversify(chunks, k=5)

    headings = [c.section_heading for c in result]
    assert "Chapter 18" in headings
    assert "Chapter 1" in headings
    assert len(result) == 5


def test_diversify_fewer_candidates_than_k():
    """_diversify returns all candidates when fewer than k."""
    from app.services.retriever import _diversify

    chunks = [
        ScoredChunk(f"c{i}", "d", f"t{i}", "Section A", 0, 0.5, "vector")
        for i in range(3)
    ]
    result = _diversify(chunks, k=10)
    assert len(result) == 3


def test_diversify_round_robin_visits_sections_by_relevance():
    """_diversify picks from more-relevant sections first in round-robin."""
    from app.services.retriever import _diversify

    # Section B has higher scores than Section A
    chunks = [
        ScoredChunk("b0", "d", "text b0", "Section B", 0, 0.9, "vector"),
        ScoredChunk("b1", "d", "text b1", "Section B", 0, 0.8, "vector"),
        ScoredChunk("b2", "d", "text b2", "Section B", 0, 0.7, "vector"),
        ScoredChunk("b3", "d", "text b3", "Section B", 0, 0.6, "vector"),
        ScoredChunk("b4", "d", "text b4", "Section B", 0, 0.55, "vector"),
        ScoredChunk("a0", "d", "text a0", "Section A", 0, 0.5, "vector"),
        ScoredChunk("a1", "d", "text a1", "Section A", 0, 0.4, "vector"),
    ]
    # Top-5 all from Section B → concentration = 1.0 → diversity kicks in
    result = _diversify(chunks, k=4)

    assert len(result) == 4
    # Section B (most relevant) leads each round
    assert result[0].chunk_id == "b0"
    assert result[1].chunk_id == "a0"
    assert result[2].chunk_id == "b1"
    assert result[3].chunk_id == "a1"
