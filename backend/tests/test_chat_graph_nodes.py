"""Tests for S78 strategy nodes (app/runtime/chat_graph.py).

(a) test_summary_node_returns_executive_summary:
    Insert a SummaryModel row with mode='executive', run summary_node,
    assert state.section_context == summary content.

(b) test_summary_node_falls_through_when_no_summary:
    No summary in DB → summary_node sets intent='factual'.

(c) test_graph_node_falls_through_on_kuzu_error:
    Mock KuzuService to raise exception → no exception propagates,
    intent overridden to 'factual'.

(d) test_search_node_augments_chunks_with_section_summaries:
    Insert SectionSummaryModel rows; mock retriever to return chunks with matching
    section_headings; assert output chunk texts contain '---' separator.

(e) test_comparative_node_interleaves_results:
    Mock retriever to return 3 chunks per side; assert state.chunks interleaves them.

(f) test_synthesize_node_calls_litellm:
    Mock LiteLLM; run synthesize_node with chunks present;
    assert get_llm_service().generate was called.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, SectionModel, SectionSummaryModel, SummaryModel
from app.runtime.chat_graph import (
    comparative_node,
    graph_node,
    search_node,
    summary_node,
    synthesize_node,
)
from app.types import ScoredChunk

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_llm_calls():
    """Globally mock LLM calls in this file to avoid CI failures when Ollama is offline."""
    with (
        patch(
            "app.runtime.chat_graph._llm_classify_fallback",
            new=AsyncMock(side_effect=lambda q, d, **kwargs: d),
        ),
        patch(
            "app.runtime.chat_graph._decompose_comparison",
            new=AsyncMock(
                return_value={"sides": ["side_a", "side_b"], "topic": "comparison"}
            ),
        ),
    ):
        yield


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


def _make_state(**overrides) -> dict:
    base = {
        "question": "What is this about?",
        "doc_ids": [],
        "scope": "all",
        "model": None,
        "intent": "factual",
        "rewritten_question": None,
        "chunks": [],
        "section_context": None,
        "answer": "",
        "citations": [],
        "confidence": "low",
        "not_found": False,
        "_llm_prompt": None,
        "_system_prompt": None,
        "source_citations": [],
    }
    base.update(overrides)
    return base


async def _insert_doc(factory, doc_id: str, title: str = "Test Doc") -> None:
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title=title,
                format="pdf",
                content_type="book",
                word_count=1000,
                file_path=f"{doc_id}.pdf",
                file_hash="abc",
                stage="complete",
                page_count=10,
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# (a) test_summary_node_returns_executive_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_node_sets_answer_directly(test_db):
    """summary_node sets section_context from exec summary so synthesize_node can tailor it.
    """
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, doc_id)

    summary_content = "This book covers the history of ancient Rome."
    async with factory() as session:
        session.add(
            SummaryModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                mode="executive",
                content=summary_content,
            )
        )
        await session.commit()

    state = _make_state(doc_ids=[doc_id], scope="single", intent="summary")
    result = await summary_node(state)

    # answer should not be set directly
    assert not result.get("answer")
    assert result.get("chunks") == []
    # section_context must contain the summary
    assert summary_content in result.get("section_context", "")


# ---------------------------------------------------------------------------
# (b) test_summary_node_falls_through_when_no_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_node_falls_through_when_no_summary(test_db):
    """No executive summary in DB → summary_node sets intent='factual'."""
    state = _make_state(doc_ids=[str(uuid.uuid4())], scope="single", intent="summary")
    result = await summary_node(state)

    assert result.get("intent") == "factual"
    assert "section_context" not in result or result.get("section_context") is None


# ---------------------------------------------------------------------------
# (c) test_graph_node_falls_through_on_kuzu_error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_node_falls_through_on_kuzu_error(test_db):
    """Kuzu raises → graph_node does not propagate, sets intent='factual'."""
    mock_service = MagicMock()
    mock_service._conn.execute.side_effect = RuntimeError("Kuzu offline")

    with patch(
        "app.services.graph.get_graph_service", return_value=mock_service
    ):
        state = _make_state(
            question="How are Achilles and Patroclus related?",
            intent="relational",
        )
        result = await graph_node(state)

    assert result.get("intent") == "factual"


# ---------------------------------------------------------------------------
# (d) test_search_node_augments_chunks_with_section_summaries
# ---------------------------------------------------------------------------


def _make_scored_chunk(
    doc_id: str, section_heading: str, text: str = "chunk content"
) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=str(uuid.uuid4()),
        document_id=doc_id,
        text=text,
        section_heading=section_heading,
        page=1,
        score=0.9,
        source="vector",
    )


@pytest.mark.asyncio
async def test_search_node_augments_chunks_with_section_summaries(test_db):
    """search_node prepends section summary to chunk text when SectionSummaryModel exists."""
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, doc_id)

    heading = "Chapter 1: The Beginning"
    section_summary = "This chapter introduces the main characters."
    async with factory() as session:
        session.add(
            SectionSummaryModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                section_id=None,
                heading=heading,
                content=section_summary,
                unit_index=0,
            )
        )
        await session.commit()

    mock_chunk = _make_scored_chunk(doc_id, heading)
    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[mock_chunk])
    mock_retriever.retrieve_with_images = AsyncMock(return_value=([mock_chunk], []))

    with patch("app.runtime.chat_graph.get_retriever", return_value=mock_retriever):
        state = _make_state(
            question="What happens in the beginning?",
            doc_ids=[doc_id],
            scope="single",
        )
        result = await search_node(state)

    chunks = result.get("chunks", [])
    assert len(chunks) == 1
    augmented_text = chunks[0]["text"]
    assert "---" in augmented_text
    assert heading in augmented_text
    assert section_summary in augmented_text
    assert mock_chunk.text in augmented_text


# ---------------------------------------------------------------------------
# (e) test_comparative_node_interleaves_results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_comparative_node_interleaves_results(test_db):
    """comparative_node interleaves chunks from two sides."""
    doc_id = str(uuid.uuid4())

    def _make_chunks(label: str, count: int = 3) -> list[ScoredChunk]:
        return [
            ScoredChunk(
                chunk_id=str(uuid.uuid4()),
                document_id=doc_id,
                text=f"{label}_chunk_{i}",
                section_heading="",
                page=i,
                score=0.8,
                source="vector",
            )
            for i in range(count)
        ]

    side_a = _make_chunks("side_a")
    side_b = _make_chunks("side_b")

    mock_retriever = MagicMock()
    # Return side_a for first call, side_b for second
    mock_retriever.retrieve = AsyncMock(side_effect=[side_a, side_b])

    with patch("app.runtime.chat_graph.get_retriever", return_value=mock_retriever):
        state = _make_state(
            question="Compare side_a versus side_b",
            intent="comparative",
        )
        result = await comparative_node(state)

    chunks = result.get("chunks", [])
    # Should have 6 chunks interleaved: a0 b0 a1 b1 a2 b2
    assert len(chunks) == 6
    texts = [c["text"] for c in chunks]
    # Odd indices should be side_b, even indices should be side_a
    assert texts[0].startswith("side_a")
    assert texts[1].startswith("side_b")
    assert texts[2].startswith("side_a")
    assert texts[3].startswith("side_b")


# ---------------------------------------------------------------------------
# (f) test_synthesize_node_calls_litellm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_node_prepares_llm_prompt(test_db):
    """synthesize_node prepares _llm_prompt/_system_prompt for stream_answer() streaming.

    With the true-streaming design, synthesize_node does NOT call the LLM directly.
    It returns _llm_prompt and _system_prompt so stream_answer() can call the LLM
    streaming and yield tokens progressively to the SSE client.
    """
    doc_id = str(uuid.uuid4())
    _engine, factory, _tmp = test_db
    await _insert_doc(factory, doc_id)

    chunks = [
        {
            "chunk_id": str(uuid.uuid4()),
            "document_id": doc_id,
            "text": "Relevant passage about the topic.",
            "section_heading": "Introduction",
            "page": 1,
            "score": 0.9,
            "source": "vector",
        }
    ]
    state = _make_state(
        question="What is the answer?",
        chunks=chunks,
        intent="factual",
    )

    result = await synthesize_node(state)

    # synthesize_node must return _llm_prompt and _system_prompt — no LLM call
    assert result.get("_llm_prompt"), "Expected _llm_prompt to be set"
    assert result.get("_system_prompt") is not None
    assert "What is the answer?" in result["_llm_prompt"]
    # answer should NOT be set — LLM not yet called
    assert not result.get("answer")
    assert not result.get("not_found")


# ---------------------------------------------------------------------------
# test_summary_intent_end_to_end — S78 AC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_intent_end_to_end(test_db):
    """POST /qa with summary question + cached exec summary returns HTTP 200
    with non-empty answer and confidence='medium'.

    summary_node (scope=single) now passes the cached summary as section_context
    so synthesize_node can tailor the answer to the specific question — this
    requires a mocked LLM call.  The mock returns a substantive answer so
    _split_response() derives confidence='medium' (>80 chars, no JSON block).
    """
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, doc_id)

    exec_summary = "The Iliad is an ancient Greek epic poem about the Trojan War."
    async with factory() as session:
        session.add(
            SummaryModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                mode="executive",
                content=exec_summary,
            )
        )
        await session.commit()

    mock_answer = (
        "The Iliad is an ancient Greek epic poem attributed to Homer, "
        "centering on events during the Trojan War, particularly the wrath of Achilles."
    )

    async def _mock_stream(*args, **kwargs):
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = mock_answer

        async def _gen():
            yield chunk

        return _gen()

    with patch("litellm.acompletion", new=AsyncMock(side_effect=_mock_stream)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/qa",
                json={
                    "question": "summarize this document",
                    "document_ids": [doc_id],
                    "scope": "single",
                },
            )

    assert resp.status_code == 200

    # Parse SSE events
    events = [line for line in resp.text.splitlines() if line.startswith("data: ")]
    assert events, "No SSE events in response"

    done_payload = json.loads(events[-1][len("data: "):])
    assert done_payload.get("done") is True, f"Last event is not done: {done_payload}"
    assert done_payload.get("answer"), f"Expected non-empty answer, got: {done_payload}"
    assert done_payload.get("confidence") in ("high", "medium"), (
        f"Expected confidence='high' or 'medium', got: {done_payload.get('confidence')}"
    )


# ---------------------------------------------------------------------------
# test_synthesize_node_collects_citations_deduplicated — S148 AC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_node_collects_citations_deduplicated(test_db):
    """synthesize_node with 3 chunks across 2 sections emits exactly 2 SourceCitation entries.

    Chunks c1 and c3 share section_id S1; chunk c2 has section_id S2.
    Expected: source_citations list has 2 entries (one per unique section_id).
    """
    _engine, factory, _tmp = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, doc_id)

    section_id_1 = str(uuid.uuid4())
    section_id_2 = str(uuid.uuid4())
    chunk_id_1 = str(uuid.uuid4())
    chunk_id_2 = str(uuid.uuid4())
    chunk_id_3 = str(uuid.uuid4())

    async with factory() as session:
        session.add(SectionModel(
            id=section_id_1, document_id=doc_id, heading="Chapter One",
            level=1, section_order=0,
        ))
        session.add(SectionModel(
            id=section_id_2, document_id=doc_id, heading="Chapter Two",
            level=1, section_order=1,
        ))
        session.add(ChunkModel(
            id=chunk_id_1, document_id=doc_id, section_id=section_id_1,
            text="text1", chunk_index=0, pdf_page_number=5,
        ))
        session.add(ChunkModel(
            id=chunk_id_2, document_id=doc_id, section_id=section_id_2,
            text="text2", chunk_index=1, pdf_page_number=10,
        ))
        session.add(ChunkModel(
            id=chunk_id_3, document_id=doc_id, section_id=section_id_1,
            text="text3", chunk_index=2, pdf_page_number=5,
        ))
        await session.commit()

    chunks = [
        {"chunk_id": chunk_id_1, "document_id": doc_id, "text": "text1",
         "section_heading": "Chapter One", "page": 5, "score": 0.9, "source": "vector"},
        {"chunk_id": chunk_id_2, "document_id": doc_id, "text": "text2",
         "section_heading": "Chapter Two", "page": 10, "score": 0.8, "source": "vector"},
        {"chunk_id": chunk_id_3, "document_id": doc_id, "text": "text3",
         "section_heading": "Chapter One", "page": 5, "score": 0.7, "source": "vector"},
    ]
    state = _make_state(
        question="What happens in these chapters?",
        chunks=chunks,
        doc_ids=[doc_id],
        intent="factual",
    )

    result = await synthesize_node(state)

    assert result.get("_llm_prompt"), "Expected _llm_prompt to be set"
    source_citations = result.get("source_citations", [])
    assert len(source_citations) == 2, (
        f"Expected 2 deduplicated source citations, got {len(source_citations)}: {source_citations}"
    )
    section_ids_in_citations = {c["section_id"] for c in source_citations}
    assert section_id_1 in section_ids_in_citations
    assert section_id_2 in section_ids_in_citations

    # S157: section_preview_snippet must be populated from chunk text (first 150 chars)
    for c in source_citations:
        assert "section_preview_snippet" in c, (
            f"Missing section_preview_snippet in citation: {c}"
        )
        snippet = c["section_preview_snippet"]
        assert isinstance(snippet, str), "section_preview_snippet must be a string"
        assert len(snippet) <= 150, (
            f"section_preview_snippet exceeds 150 chars: {len(snippet)}"
        )
    # The first citation (chunk c1, text='text1') has snippet 'text1'
    first_cit = next(c for c in source_citations if c["section_id"] == section_id_1)
    assert first_cit["section_preview_snippet"] == "text1"
