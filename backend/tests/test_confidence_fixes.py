"""Tests for S83: confidence fixes and multi-doc scope improvements.

(a) test_library_summary_missing_returns_medium:
    summary_node with scope='all' and no LibrarySummaryModel returns
    confidence='medium' and 'being generated' in answer.

(b) test_split_response_defaults_medium_for_long_answer:
    _split_response with a long answer (>80 chars) and no JSON block
    returns confidence='medium'.

(c) test_split_response_defaults_low_for_short_answer:
    _split_response('I do not know.') returns confidence='low'.

(d) test_cap_per_document_limits_chunks:
    _cap_per_document with 6 chunks from 2 documents (3 each), max_per_doc=2
    returns 4 chunks with at most 2 per doc_id.

(e) test_search_node_caps_multi_doc_chunks:
    search_node with scope='all' and retriever returning 5 chunks from the
    same doc_id returns at most 2 from that document.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import DocumentModel, LibrarySummaryModel
from app.runtime.chat_graph import search_node, summary_node
from app.services.context_packer import _cap_per_document
from app.services.qa import _split_response
from app.types import ScoredChunk

# ---------------------------------------------------------------------------
# Shared DB fixture
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

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


async def _insert_document(factory, doc_id: str) -> None:
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test Doc",
                format="txt",
                content_type="book",
                word_count=1000,
                page_count=10,
                file_path="/tmp/test.txt",
                stage="complete",
                tags=[],
            )
        )
        await session.commit()


def _make_scored_chunk(doc_id: str, text: str = "Some text content.", i: int = 0) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=str(uuid.uuid4()),
        document_id=doc_id,
        text=text,
        section_heading=None,
        page=i,
        score=0.9 - i * 0.1,
        source="vector",
    )


# ---------------------------------------------------------------------------
# (a) test_library_summary_missing_returns_medium
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_library_summary_missing_returns_medium(test_db):
    """summary_node with scope='all' and no LibrarySummaryModel returns medium confidence."""
    state = {
        "question": "Summarize all documents",
        "scope": "all",
        "doc_ids": [],
        "intent": "summary",
    }

    # Mock _fetch_library_executive_summary to return None (avoids DB call)
    # Mock asyncio.create_task to avoid running the background LLM task.
    # The side_effect closes the coroutine so Python does not emit
    # "RuntimeWarning: coroutine was never awaited".
    mock_task = MagicMock()
    mock_task.add_done_callback = MagicMock()

    def _fake_create_task(coro, **kwargs):
        # Close the coroutine immediately to satisfy Python's unawaited-coroutine
        # detector, then return the mock task so the production code can call
        # add_done_callback on it without error.
        coro.close()
        return mock_task

    with (
        patch(
            "app.runtime.chat_graph._fetch_library_executive_summary",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.runtime.chat_graph.asyncio.create_task",
            side_effect=_fake_create_task,
        ) as mock_create_task,
    ):
        result = await summary_node(state)

    assert result.get("confidence") == "medium", (
        f"Expected confidence='medium', got {result.get('confidence')!r}"
    )
    assert "being generated" in result.get("answer", "").lower(), (
        f"Expected 'being generated' in answer, got {result.get('answer')!r}"
    )
    # Background task should have been fired
    assert mock_create_task.call_count >= 1


@pytest.mark.asyncio
async def test_library_summary_present_returns_high(test_db):
    """summary_node with scope='all' and existing LibrarySummaryModel returns confidence='high'."""
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    await _insert_document(factory, doc_id)

    # Insert a LibrarySummaryModel row
    async with factory() as session:
        session.add(
            LibrarySummaryModel(
                id=str(uuid.uuid4()),
                mode="executive",
                content="Thematic overview of all documents in the library.",
            )
        )
        await session.commit()

    state = {
        "question": "Summarize all documents",
        "scope": "all",
        "doc_ids": [],
        "intent": "summary",
    }

    result = await summary_node(state)

    assert result.get("confidence") == "high", (
        f"Expected confidence='high', got {result.get('confidence')!r}"
    )
    assert "Thematic overview" in result.get("answer", ""), (
        "Expected library summary content in answer"
    )


# ---------------------------------------------------------------------------
# (b) test_split_response_defaults_medium_for_long_answer
# ---------------------------------------------------------------------------


def test_split_response_defaults_medium_for_long_answer():
    """Long answer (>80 chars) with no JSON block → confidence='medium'."""
    long_answer = (
        "Holmes examined the room carefully and noted several clues that pointed "
        "toward the culprit's identity and motive in the case of the missing coronet."
    )
    assert len(long_answer) > 80

    answer, citations, confidence = _split_response(long_answer)

    assert confidence == "medium", f"Expected 'medium', got {confidence!r}"
    assert citations == []
    assert answer == long_answer


# ---------------------------------------------------------------------------
# (c) test_split_response_defaults_low_for_short_answer
# ---------------------------------------------------------------------------


def test_split_response_defaults_low_for_short_answer():
    """Short answer (<=80 chars) with no JSON block → confidence='low'."""
    short_answer = "I do not know."
    assert len(short_answer) <= 80

    answer, citations, confidence = _split_response(short_answer)

    assert confidence == "low", f"Expected 'low', got {confidence!r}"


def test_split_response_empty_answer_is_low():
    """Empty answer → confidence='low'."""
    _, _, confidence = _split_response("")
    assert confidence == "low"


# ---------------------------------------------------------------------------
# (d) test_cap_per_document_limits_chunks
# ---------------------------------------------------------------------------


def test_cap_per_document_limits_chunks():
    """_cap_per_document with 6 chunks (3 per doc) → 4 chunks (2 per doc)."""
    doc_a = str(uuid.uuid4())
    doc_b = str(uuid.uuid4())

    chunks = [{"document_id": doc_a, "text": f"Doc A chunk {i}"} for i in range(3)] + [
        {"document_id": doc_b, "text": f"Doc B chunk {i}"} for i in range(3)
    ]

    result = _cap_per_document(chunks, max_per_doc=2)

    assert len(result) == 4, f"Expected 4 chunks, got {len(result)}"

    doc_a_count = sum(1 for c in result if c["document_id"] == doc_a)
    doc_b_count = sum(1 for c in result if c["document_id"] == doc_b)
    assert doc_a_count <= 2, f"doc_a has {doc_a_count} chunks (expected <= 2)"
    assert doc_b_count <= 2, f"doc_b has {doc_b_count} chunks (expected <= 2)"


def test_cap_per_document_preserves_order():
    """_cap_per_document preserves original ordering within the cap."""
    doc_id = str(uuid.uuid4())
    chunks = [
        {"document_id": doc_id, "text": f"chunk {i}", "score": 1.0 - i * 0.1} for i in range(4)
    ]

    result = _cap_per_document(chunks, max_per_doc=2)

    assert len(result) == 2
    # First two chunks should be kept (order preserved)
    assert result[0]["text"] == "chunk 0"
    assert result[1]["text"] == "chunk 1"


# ---------------------------------------------------------------------------
# (e) test_search_node_caps_multi_doc_chunks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_node_caps_multi_doc_chunks(test_db):
    """search_node with scope='all' caps output at 2 chunks per document_id."""
    doc_id = str(uuid.uuid4())

    # Mock retriever returns 5 chunks all from the same document
    five_chunks = [_make_scored_chunk(doc_id, f"chunk text {i}", i) for i in range(5)]

    mock_retriever = AsyncMock()
    mock_retriever.retrieve = AsyncMock(return_value=five_chunks)

    state = {
        "question": "What happens in the story?",
        "scope": "all",
        "doc_ids": [],
        "intent": "factual",
    }

    with (
        patch("app.runtime.chat_graph.get_retriever", return_value=mock_retriever),
        patch(
            "app.runtime.chat_graph._fetch_section_summaries",
            new_callable=AsyncMock,
            return_value={},
        ),
    ):
        result = await search_node(state)

    chunks_out = result.get("chunks", [])
    doc_id_chunks = [c for c in chunks_out if c.get("document_id") == doc_id]
    assert len(doc_id_chunks) <= 2, (
        f"Expected at most 2 chunks from same doc, got {len(doc_id_chunks)}"
    )
