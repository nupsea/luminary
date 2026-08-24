"""S70 — Ingestion performance tests.

Verifies:
1. Embedding uses a single batch encode call (not per-chunk loop).
2. Summarization is fire-and-forget: document reaches stage=complete before
   any summary is written to the DB.
3. All chunks are written to SQLite in a single batch (add_all) per document.
"""

import asyncio
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel, SummaryModel
from app.workflows.ingestion import IngestionState, chunk_node, embed_node, summarize_node

# Shared DB fixture


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
    yield engine, factory, tmp_path
    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


async def _insert_document(factory, doc_id: str, tmp_path: Path) -> None:
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Perf Test Doc",
                format="txt",
                content_type="notes",
                word_count=200,
                page_count=2,
                file_path=str(tmp_path / "doc.txt"),
                stage="embedding",
            )
        )
        await session.commit()


# 1. Embedding batch test


@pytest.mark.asyncio
async def test_embedding_called_in_batch(test_db):
    """embed_node must call embedder.encode exactly once with all chunk texts."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id, tmp_path)

    n_chunks = 10
    chunks = [
        {"id": str(uuid.uuid4()), "document_id": doc_id, "text": f"chunk text {i}", "index": i}
        for i in range(n_chunks)
    ]

    state: IngestionState = {
        "document_id": doc_id,
        "file_path": str(tmp_path / "doc.txt"),
        "format": "txt",
        "parsed_document": None,
        "content_type": "notes",
        "chunks": chunks,
        "status": "embedding",
        "error": None,
    }

    encode_calls: list[list[str]] = []

    class TrackingEmbedder:
        def encode(self, texts: list[str]) -> list[list[float]]:
            encode_calls.append(list(texts))
            return [[0.1] * 1024 for _ in texts]

    class FakeLanceDB:
        def upsert_chunks(self, rows):
            pass

    with (
        patch("app.services.embedder.get_embedding_service", return_value=TrackingEmbedder()),
        patch("app.services.vector_store.get_lancedb_service", return_value=FakeLanceDB()),
    ):
        await embed_node(state)

    # encode must have been called exactly once
    assert len(encode_calls) == 1, f"Expected 1 encode call, got {len(encode_calls)}"
    # with all chunk texts in that single call
    assert encode_calls[0] == [c["text"] for c in chunks]


@pytest.mark.asyncio
async def test_embedding_never_holds_more_than_a_batch(test_db):
    """Peak memory must be a batch, not a document.

    embed_node used to encode every chunk in one call and then materialise every
    row before writing any, so the document's text was live three times over --
    the chunk list, the encoder input and the rows -- plus one vector per chunk.
    Only the LanceDB write was bounded, which is why the code carries a note
    about a 9400-chunk Bible: this limit was met here once and only the last
    step was fixed.

    Asserted structurally rather than by watching RSS. Measured at node
    granularity, the change is swamped: entity_extract_node spikes 2.3GB
    transiently in the same pass, and three runs of similar code gave embed
    deltas of +0.43, +0.97 and +1.87GB. The bound is the thing that is true
    regardless of what the allocator does with it.
    """
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id, tmp_path)

    n_chunks = 2500  # more than one batch, so the loop is exercised
    chunks = [
        {"id": str(uuid.uuid4()), "document_id": doc_id, "text": f"chunk text {i}", "index": i}
        for i in range(n_chunks)
    ]
    state: IngestionState = {
        "document_id": doc_id,
        "file_path": str(tmp_path / "doc.txt"),
        "format": "txt",
        "parsed_document": None,
        "content_type": "notes",
        "chunks": chunks,
        "status": "embedding",
        "error": None,
    }

    encode_sizes: list[int] = []
    upsert_sizes: list[int] = []

    class TrackingEmbedder:
        def encode(self, texts: list[str]) -> list[list[float]]:
            encode_sizes.append(len(texts))
            return [[0.1] * 384 for _ in texts]

    class TrackingLanceDB:
        def upsert_chunks(self, rows):
            upsert_sizes.append(len(rows))

        def count_for_document(self, _doc_id):
            return sum(upsert_sizes)

    with (
        patch("app.services.embedder.get_embedding_service", return_value=TrackingEmbedder()),
        patch("app.services.vector_store.get_lancedb_service", return_value=TrackingLanceDB()),
    ):
        result = await embed_node(state)

    assert result["status"] == "indexing", result.get("error")
    assert max(encode_sizes) <= 1000, (
        f"the encoder was handed {max(encode_sizes)} texts at once; peak memory "
        f"scales with the document again"
    )
    assert max(upsert_sizes) <= 1000
    # Still batched, not per-chunk: the defect the original test guarded.
    assert len(encode_sizes) == 3
    assert sum(encode_sizes) == n_chunks


# 2. Summarization is fire-and-forget


@pytest.mark.asyncio
async def test_summarization_is_fire_and_forget(test_db):
    """summarize_node returns immediately; stage=complete before any summary is written."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id, tmp_path)

    # Replace _run_pregenerate with a coroutine that sleeps forever (never stores summaries)
    never_done: asyncio.Future = asyncio.get_event_loop().create_future()

    async def _slow_pregenerate(doc_id: str) -> None:
        await never_done  # never resolves in this test

    with patch("app.workflows.ingestion._run_pregenerate", side_effect=_slow_pregenerate):
        state: IngestionState = {
            "document_id": doc_id,
            "file_path": str(tmp_path / "doc.txt"),
            "format": "txt",
            "parsed_document": None,
            "content_type": "notes",
            "chunks": [],
            "status": "complete",
            "error": None,
        }
        result = await summarize_node(state)

    # The node must return immediately — state unchanged
    assert result["status"] == "complete"

    # No summaries in DB (background task hasn't run yet)
    async with factory() as session:
        count = (
            (await session.execute(select(SummaryModel).where(SummaryModel.document_id == doc_id)))
            .scalars()
            .all()
        )
    assert len(count) == 0, "Summaries written synchronously — should be fire-and-forget"

    # Clean up pending task so event loop doesn't complain
    never_done.cancel()
    await asyncio.sleep(0)  # let the cancelled task settle


# 3. Chunks written in batch (add_all)


@pytest.mark.asyncio
async def test_chunks_written_in_batch(test_db):
    """chunk_node persists all N chunks in one batch — verified via functional check."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Batch Test",
                format="txt",
                content_type="notes",
                word_count=500,
                page_count=1,
                file_path=str(tmp_path / "doc.txt"),
                stage="chunking",
            )
        )
        await session.commit()

    # Build a state with enough text to produce multiple chunks
    long_text = " ".join(f"word{i}" for i in range(500))
    state: IngestionState = {
        "document_id": doc_id,
        "file_path": str(tmp_path / "doc.txt"),
        "format": "txt",
        "content_type": "notes",
        "parsed_document": {
            "title": "Batch Test",
            "format": "txt",
            "pages": 1,
            "word_count": 500,
            "sections": [
                {"heading": "Intro", "level": 1, "text": long_text, "page_start": 0, "page_end": 1}
            ],
            "raw_text": long_text,
        },
        "chunks": None,
        "status": "chunking",
        "error": None,
    }

    result = await chunk_node(state)

    # All chunks must be in the DB
    async with factory() as session:
        db_chunks = (
            (await session.execute(select(ChunkModel).where(ChunkModel.document_id == doc_id)))
            .scalars()
            .all()
        )

    in_state = result.get("chunks") or []
    assert len(db_chunks) == len(in_state), (
        f"DB has {len(db_chunks)} chunks but state has {len(in_state)}"
    )
    assert len(db_chunks) > 0, "chunk_node produced no chunks"
