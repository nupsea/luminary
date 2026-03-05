"""Tests for context expansion — adjacent chunk fetching after RRF (S57).

(a) test_expand_adds_neighbors: neighbors at index±1 appear with score=original*0.75
(b) test_expand_dedup_keeps_higher_score: chunk in both retrieval and expansion → keep higher score
(c) test_expand_skipped_for_code: content_type='code' → no expansion
(d) test_expand_capped_at_k_times_2
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel
from app.services.retriever import _expand_context
from app.types import ScoredChunk

# ---------------------------------------------------------------------------
# Fixture — in-memory DB with documents and chunks
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
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

    yield engine, factory

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


def _make_doc(doc_id: str, content_type: str = "book") -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title="Test Doc",
        format="txt",
        content_type=content_type,
        word_count=100,
        page_count=0,
        file_path="/tmp/test.txt",
        stage="complete",
        tags=[],
    )


def _make_chunk(doc_id: str, idx: int, text: str, chunk_id: str | None = None) -> ChunkModel:
    return ChunkModel(
        id=chunk_id or str(uuid.uuid4()),
        document_id=doc_id,
        section_id=None,
        text=text,
        token_count=len(text.split()),
        page_number=0,
        speaker=None,
        chunk_index=idx,
    )


def _scored(
    chunk_id: str,
    document_id: str,
    text: str,
    score: float = 0.8,
    chunk_index: int = 0,
) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        section_heading="",
        page=0,
        score=score,
        source="vector",
        chunk_index=chunk_index,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_expand_adds_neighbors(test_db):
    """Neighbors at chunk_index ± 1 appear in output with score = original * 0.75."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())

    chunk_ids = [str(uuid.uuid4()) for _ in range(5)]
    async with factory() as session:
        session.add(_make_doc(doc_id, "book"))
        for i, cid in enumerate(chunk_ids):
            session.add(_make_chunk(doc_id, i, f"text chunk {i}", cid))
        await session.commit()

    # Retrieve chunk at index 2 with score 0.8
    input_chunks = [_scored(chunk_ids[2], doc_id, "text chunk 2", score=0.8, chunk_index=2)]
    result = await _expand_context(input_chunks, k=5)

    result_ids = {c.chunk_id for c in result}
    # Neighbors at index 1 and 3 should appear
    assert chunk_ids[1] in result_ids, "Left neighbor (index 1) should be in expansion"
    assert chunk_ids[3] in result_ids, "Right neighbor (index 3) should be in expansion"

    # Neighbor scores should be 0.75 * 0.8 = 0.6
    for c in result:
        if c.chunk_id in (chunk_ids[1], chunk_ids[3]):
            assert abs(c.score - 0.6) < 1e-6, (
                f"Neighbor score expected 0.6, got {c.score}"
            )
            assert c.source == "context_expansion"


@pytest.mark.anyio
async def test_expand_dedup_keeps_higher_score(test_db):
    """If a neighbor is already in the result set, keep whichever has the higher score."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())

    chunk_ids = [str(uuid.uuid4()) for _ in range(3)]
    async with factory() as session:
        session.add(_make_doc(doc_id, "book"))
        for i, cid in enumerate(chunk_ids):
            session.add(_make_chunk(doc_id, i, f"text {i}", cid))
        await session.commit()

    # Both chunk 0 and chunk 2 are in the input; chunk 1 is the neighbor of both.
    # chunk 0 score=0.9 → neighbor chunk 1 gets 0.675
    # chunk 2 score=0.4 → neighbor chunk 1 gets 0.3
    # chunk 1 is NOT independently retrieved (not in input list)
    input_chunks = [
        _scored(chunk_ids[0], doc_id, "text 0", score=0.9, chunk_index=0),
        _scored(chunk_ids[2], doc_id, "text 2", score=0.4, chunk_index=2),
    ]
    result = await _expand_context(input_chunks, k=5)

    # chunk 1 should appear exactly once with the higher score (0.675)
    chunk_1_results = [c for c in result if c.chunk_id == chunk_ids[1]]
    assert len(chunk_1_results) == 1, "Chunk 1 should appear exactly once (dedup)"
    assert abs(chunk_1_results[0].score - 0.9 * 0.75) < 1e-6, (
        f"Expected deduped score {0.9 * 0.75}, got {chunk_1_results[0].score}"
    )


@pytest.mark.anyio
async def test_expand_skipped_for_code(test_db):
    """No expansion for content_type='code'."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())

    chunk_ids = [str(uuid.uuid4()) for _ in range(3)]
    async with factory() as session:
        session.add(_make_doc(doc_id, "code"))
        for i, cid in enumerate(chunk_ids):
            session.add(_make_chunk(doc_id, i, f"def func_{i}(): pass", cid))
        await session.commit()

    input_chunks = [_scored(chunk_ids[1], doc_id, "def func_1(): pass", score=0.9, chunk_index=1)]
    result = await _expand_context(input_chunks, k=5)

    # Only original chunk should be present (no expansion)
    assert len(result) == 1, f"Expected no expansion for code, got {len(result)} chunks"
    assert result[0].chunk_id == chunk_ids[1]


@pytest.mark.anyio
async def test_expand_capped_at_k_times_2(test_db):
    """Total expansion result is capped at k * 2."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    k = 3  # cap = 6

    # Create many chunks so expansion adds many neighbors
    chunk_ids = [str(uuid.uuid4()) for _ in range(20)]
    async with factory() as session:
        session.add(_make_doc(doc_id, "book"))
        for i, cid in enumerate(chunk_ids):
            session.add(_make_chunk(doc_id, i, f"chunk text {i}", cid))
        await session.commit()

    # Input: 5 chunks (indices 5, 7, 9, 11, 13) — each adds 2 neighbors → up to 15 total
    input_chunks = [
        _scored(chunk_ids[i], doc_id, f"chunk text {i}", score=0.8, chunk_index=i)
        for i in [5, 7, 9, 11, 13]
    ]
    result = await _expand_context(input_chunks, k=k)

    assert len(result) <= k * 2, (
        f"Expected at most {k * 2} chunks, got {len(result)}"
    )
