"""Tests for QAService and POST /qa endpoint.

V2: stream_answer() delegates to the LangGraph chat router.  Integration tests
that exercise stream_answer() now mock app.runtime.chat_graph.get_chat_graph
with a mock graph whose ainvoke() returns a pre-built result dict.

Pure helper-function tests (_split_response, _build_context, etc.) are
unchanged — they test stateless functions that are still in qa.py.
"""

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, QAHistoryModel
from app.services.qa import (
    NOT_FOUND_SENTINEL,
    QA_SYSTEM_PROMPT,
    QAService,
    _build_context,
    _enrich_citation_titles,
    _should_use_summary,
    _split_response,
)
from app.types import ScoredChunk

# ---------------------------------------------------------------------------
# Shared DB fixture
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


async def _insert_doc(factory, tmp_path: Path, doc_id: str, title: str = "Test Doc") -> None:
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title=title,
                format="txt",
                content_type="notes",
                word_count=100,
                page_count=2,
                file_path=str(tmp_path / "doc.txt"),
                stage="complete",
            )
        )
        await session.commit()


def _make_chunk(doc_id: str, text: str = "chunk text", section: str = "Intro") -> ScoredChunk:
    return ScoredChunk(
        chunk_id=str(uuid.uuid4()),
        document_id=doc_id,
        text=text,
        section_heading=section,
        page=1,
        score=0.9,
        source="vector",
    )


def _make_graph_result(
    *,
    answer: str = "The answer.",
    citations: list | None = None,
    confidence: str = "high",
    not_found: bool = False,
    chunks: list | None = None,
    intent: str = "factual",
) -> dict:
    """Build a mock graph result that matches ChatState shape."""
    return {
        "question": "",
        "doc_ids": [],
        "scope": "single",
        "model": None,
        "intent": intent,
        "rewritten_question": None,
        "chunks": chunks or [],
        "section_context": None,
        "answer": answer,
        "citations": citations or [],
        "confidence": confidence,
        "not_found": not_found,
    }


def _make_mock_graph(result: dict) -> MagicMock:
    """Return a mock graph whose ainvoke returns `result`."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=result)
    return mock_graph


async def _async_iter(items):
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# _split_response — unit tests (unchanged)
# ---------------------------------------------------------------------------


def test_split_response_extracts_answer_and_citations():
    citations = [{"document_title": "Bio", "section_heading": "Cells", "page": 1, "excerpt": "..."}]
    full_text = 'The cell is alive.' + json.dumps({"citations": citations, "confidence": "high"})
    answer, parsed_citations, confidence = _split_response(full_text)
    assert answer == "The cell is alive."
    assert len(parsed_citations) == 1
    assert parsed_citations[0]["document_title"] == "Bio"
    assert confidence == "high"


def test_split_response_no_json_returns_full_text():
    full_text = "The answer is here."
    answer, citations, confidence = _split_response(full_text)
    assert answer == full_text
    assert citations == []
    assert confidence == "low"


def test_split_response_medium_confidence():
    citations: list = []
    full_text = "Partial answer." + json.dumps({"citations": citations, "confidence": "medium"})
    _, _, confidence = _split_response(full_text)
    assert confidence == "medium"


def test_split_response_malformed_json_returns_empty_citations():
    full_text = 'Answer text.{"citations": [invalid json'
    answer, citations, confidence = _split_response(full_text)
    assert citations == []
    assert confidence == "low"


def test_split_response_strips_json_label_line():
    citations = [{"document_title": "Bio", "section_heading": "Cells", "page": 1, "excerpt": "..."}]
    full_text = "The cell is the basic unit of life.\nJSON:\n" + json.dumps(
        {"citations": citations, "confidence": "high"}
    )
    answer, _, _ = _split_response(full_text)
    assert answer == "The cell is the basic unit of life."


def test_split_response_strips_instruction_echo():
    citations: list = []
    full_text = (
        "ONLY JSON (no prose inside the JSON, do not repeat the answer):\n"
        + json.dumps({"citations": citations, "confidence": "medium"})
    )
    answer, _, _ = _split_response(full_text)
    assert answer == ""


def test_split_response_strips_here_is_json_label():
    citations: list = []
    full_text = "Alice explores Wonderland.\nHere is a JSON response:\n" + json.dumps(
        {"citations": citations, "confidence": "high"}
    )
    answer, _, _ = _split_response(full_text)
    assert answer == "Alice explores Wonderland."


def test_split_response_style_b_answer_in_json():
    citations = [{"document_title": "Gita", "section_heading": "Ch1", "page": 1, "excerpt": "..."}]
    full_text = json.dumps(
        {"answer": "Arjuna questions his duty.", "citations": citations, "confidence": "medium"}
    )
    answer, parsed_citations, confidence = _split_response(full_text)
    assert answer == "Arjuna questions his duty."
    assert len(parsed_citations) == 1
    assert confidence == "medium"


def test_split_response_prose_with_colon_not_stripped():
    citations: list = []
    full_text = "The main themes are:\n- Adventure\n- Mystery.\n" + json.dumps(
        {"citations": citations, "confidence": "medium"}
    )
    answer, _, _ = _split_response(full_text)
    assert "main themes" in answer


# ---------------------------------------------------------------------------
# _build_context — unit tests (unchanged)
# ---------------------------------------------------------------------------


def test_build_context_includes_document_title():
    chunk = _make_chunk("doc1", text="ATP is produced in the mitochondria.", section="Energy")
    context = _build_context([chunk], {"doc1": "Cell Biology"})
    assert "Cell Biology" in context
    assert "Energy" in context
    assert "ATP is produced" in context


def test_build_context_fallback_uses_document_id():
    chunk = _make_chunk("doc-unknown")
    context = _build_context([chunk], {})
    assert "doc-unknown" in context


def test_qa_system_prompt_contains_not_found_sentinel():
    assert NOT_FOUND_SENTINEL in QA_SYSTEM_PROMPT


def test_qa_system_prompt_mentions_citations():
    assert "citations" in QA_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# QAService.stream_answer — normal flow
# V2: mock the chat graph (graph.ainvoke returns pre-built result)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_yields_token_events_for_answer(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Biology Book")

    citations = [
        {"document_title": "Biology Book", "section_heading": "Cells", "page": 1, "excerpt": "..."}
    ]
    result = _make_graph_result(answer="Mitochondria produces ATP.", citations=citations)
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [
            e async for e in svc.stream_answer(
                "What does mitochondria do?", [doc_id], "single", None
            )
        ]

    assert len(events) >= 2
    token_events = [e for e in events if '"token"' in e]
    assert len(token_events) > 0
    for event in token_events:
        assert event.startswith("data: ")
        payload = json.loads(event[len("data: "):])
        assert "token" in payload


@pytest.mark.asyncio
async def test_stream_final_event_contains_citations(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Physics")

    citations = [
        {"document_title": None, "section_heading": "Forces", "page": 5, "excerpt": "F=ma"}
    ]
    result = _make_graph_result(
        answer="Force equals mass times acceleration.",
        citations=citations,
        confidence="high",
    )
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [
            e async for e in svc.stream_answer(
                "What is Newton's 2nd law?", [doc_id], "single", None
            )
        ]

    done_payload = json.loads(events[-1][len("data: "):])
    assert done_payload["done"] is True
    assert done_payload["confidence"] == "high"
    assert len(done_payload["citations"]) == 1
    assert "qa_id" in done_payload


@pytest.mark.asyncio
async def test_stream_stores_qa_in_database(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "History")

    result = _make_graph_result(answer="Napoleon was French.", confidence="medium")
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [e async for e in svc.stream_answer("Who was Napoleon?", [doc_id], "single", None)]

    done_payload = json.loads(events[-1][len("data: "):])
    qa_id = done_payload["qa_id"]

    async with factory() as session:
        result_row = await session.execute(select(QAHistoryModel).where(QAHistoryModel.id == qa_id))
        stored = result_row.scalar_one_or_none()

    assert stored is not None
    assert stored.question == "Who was Napoleon?"
    assert "Napoleon" in stored.answer
    assert stored.confidence == "medium"


# ---------------------------------------------------------------------------
# QAService.stream_answer — NOT_FOUND flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_found_yields_not_found_event(test_db):
    _engine, factory, tmp_path = test_db

    # Chunks present but LLM said NOT_FOUND → not_found event (not error event)
    result = _make_graph_result(
        answer="",
        not_found=True,
        chunks=[{"chunk_id": "c1", "document_id": "d1", "text": "x",
                 "section_heading": "S", "page": 1, "score": 0.5, "source": "vector"}],
    )
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [e async for e in svc.stream_answer("Unknown question?", None, "all", None)]

    assert len(events) == 1
    payload = json.loads(events[0][len("data: "):])
    assert payload["done"] is True
    assert payload["not_found"] is True


@pytest.mark.asyncio
async def test_not_found_no_token_events(test_db):
    _engine, factory, tmp_path = test_db

    result = _make_graph_result(answer="", not_found=True, chunks=[])
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [e async for e in svc.stream_answer("Unknowable?", None, "all", None)]

    token_events = [e for e in events if '"token"' in e]
    assert len(token_events) == 0


# ---------------------------------------------------------------------------
# POST /qa — HTTP endpoint integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_returns_sse_content_type(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id)

    result = _make_graph_result(answer="The answer is 42.")
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/qa", json={"question": "What is the answer?"})

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_endpoint_not_found_response(test_db):
    """No chunks → no_context error event."""
    _engine, factory, tmp_path = test_db

    result = _make_graph_result(answer="", not_found=True, chunks=[])
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/qa", json={"question": "Impossible question?"})

    assert resp.status_code == 200
    events = [line for line in resp.text.splitlines() if line.startswith("data: ")]
    assert len(events) == 1
    payload = json.loads(events[0][len("data: "):])
    assert payload["error"] == "no_context"
    assert payload["done"] is True


@pytest.mark.asyncio
async def test_endpoint_all_scope_produces_answer(test_db):
    """scope='all' endpoint call produces a valid SSE response."""
    _engine, factory, tmp_path = test_db

    result = _make_graph_result(answer="An answer.", intent="factual")
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/qa",
                json={"question": "Any question?", "scope": "all", "document_ids": ["doc-1"]},
            )

    assert resp.status_code == 200
    events = [line for line in resp.text.splitlines() if line.startswith("data: ")]
    done_events = [e for e in events if '"done"' in e]
    assert len(done_events) >= 1


# ---------------------------------------------------------------------------
# QAService.stream_answer — error flows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qa_no_context(test_db):
    """Graph returns not_found=True with no chunks → 1 SSE event with error='no_context'."""
    _engine, factory, tmp_path = test_db

    result = _make_graph_result(answer="", not_found=True, chunks=[])
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [
            e async for e in svc.stream_answer("anything", ["nonexistent-doc-id"], "single", None)
        ]

    data_lines = [e for e in events if e.startswith("data: ")]
    assert len(data_lines) == 1
    payload = json.loads(data_lines[0][len("data: "):])
    assert payload["error"] == "no_context"
    assert payload["done"] is True


@pytest.mark.asyncio
async def test_qa_ollama_offline(test_db):
    """Graph raises (LLM unavailable) → SSE event with error='llm_unavailable'."""
    _engine, factory, tmp_path = test_db

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(side_effect=Exception("connection refused"))

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [
            e async for e in svc.stream_answer("What is this about?", None, "all", None)
        ]

    data_lines = [e for e in events if e.startswith("data: ")]
    assert len(data_lines) == 1
    payload = json.loads(data_lines[0][len("data: "):])
    assert payload["error"] == "llm_unavailable"
    assert payload["type"] == "error"
    assert payload["done"] is True


@pytest.mark.asyncio
async def test_s103_ollama_offline_sse_type_error(test_db):
    """S103: litellm.acompletion raises ServiceUnavailableError during Path B streaming.

    POST /qa must return HTTP 200 (SSE) with a single data event where:
    - type == 'error'
    - message contains 'Ollama is unreachable'
    - done == True
    No HTTP 500 must be returned; the SSE connection closes cleanly.
    """
    import litellm as _litellm
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id)

    # Graph returns a state that requires Path B (LLM streaming): _llm_prompt is set.
    result_with_prompt = {
        "answer": "",
        "citations": [],
        "confidence": "low",
        "not_found": False,
        "chunks": [],
        "_llm_prompt": "Answer the question.",
        "_system_prompt": "",
        "intent": "factual",
    }
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=result_with_prompt)

    # Simulate Ollama offline: acompletion raises ServiceUnavailableError.
    offline_error = _litellm.ServiceUnavailableError(
        message="Connection refused", llm_provider="ollama", model="ollama/mistral"
    )
    with (
        patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph),
        patch("litellm.acompletion", new=AsyncMock(side_effect=offline_error)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/qa",
                json={"question": "What is this about?", "document_ids": [doc_id]},
            )

    assert resp.status_code == 200, "Must return 200 (SSE), not 500"
    assert "text/event-stream" in resp.headers.get("content-type", "")

    data_lines = [ln for ln in resp.text.splitlines() if ln.startswith("data: ")]
    assert len(data_lines) == 1, f"Expected 1 error event, got: {data_lines}"
    payload = json.loads(data_lines[0][len("data: "):])
    assert payload.get("type") == "error", f"Expected type='error', got: {payload}"
    assert "Ollama is unreachable" in payload.get("message", ""), payload
    assert payload.get("done") is True


@pytest.mark.asyncio
async def test_s103_api_connection_error_sse_type_error(test_db):
    """S103: litellm.acompletion raises APIConnectionError during Path B streaming.

    APIConnectionError fires when the TCP connection is refused outright (as opposed
    to ServiceUnavailableError when the server returns 503). Both should yield the
    same type=error SSE event.
    """
    import litellm as _litellm

    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id)

    result_with_prompt = {
        "answer": "",
        "citations": [],
        "confidence": "low",
        "not_found": False,
        "chunks": [],
        "_llm_prompt": "Answer the question.",
        "_system_prompt": "",
        "intent": "factual",
    }
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=result_with_prompt)

    conn_error = _litellm.APIConnectionError(
        message="Connection refused", llm_provider="ollama", model="ollama/mistral"
    )
    with (
        patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph),
        patch("litellm.acompletion", new=AsyncMock(side_effect=conn_error)),
    ):
        svc = QAService()
        events = [e async for e in svc.stream_answer("What is this?", [doc_id], "single", None)]

    data_lines = [e for e in events if e.startswith("data: ")]
    assert len(data_lines) == 1
    payload = json.loads(data_lines[0][len("data: "):])
    assert payload.get("type") == "error"
    assert "Ollama is unreachable" in payload.get("message", "")
    assert payload.get("done") is True


@pytest.mark.asyncio
async def test_qa_with_mock_llm(test_db):
    """Happy-path: graph returns answer + citations → token events + done event."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Time Machine")

    citations = [
        {"document_title": "Time Machine", "section_heading": "Chapter 1",
         "page": 3, "excerpt": "..."}
    ]
    result = _make_graph_result(
        answer="The Time Traveller invented a machine.",
        citations=citations,
        confidence="high",
    )
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [
            e async for e in svc.stream_answer(
                "What is the time machine?", [doc_id], "single", None
            )
        ]

    token_events = [e for e in events if '"token"' in e]
    assert len(token_events) >= 1

    done_payload = json.loads(events[-1][len("data: "):])
    assert done_payload["done"] is True
    assert len(done_payload["citations"]) >= 1


# ---------------------------------------------------------------------------
# S61 — _enrich_citation_titles unit tests (unchanged)
# ---------------------------------------------------------------------------


def test_enrich_citation_titles_single_scope_clears_title():
    chunk = _make_chunk("doc-a", section="Intro")
    citations = [{"document_title": "Some Book", "section_heading": "Intro", "page": 1}]
    result = _enrich_citation_titles(citations, [chunk], {"doc-a": "Some Book"}, "single")
    assert result[0]["document_title"] is None


def test_enrich_citation_titles_all_scope_populates_from_chunks():
    chunk = _make_chunk("doc-b", section="Chapter 2")
    chunk.page = 5
    citations = [{"document_title": "", "section_heading": "Chapter 2", "page": 5}]
    result = _enrich_citation_titles(citations, [chunk], {"doc-b": "The Odyssey"}, "all")
    assert result[0]["document_title"] == "The Odyssey"


@pytest.mark.asyncio
async def test_citations_passed_through_from_graph(test_db):
    """Citations returned by graph are passed through in the done event."""
    _engine, factory, tmp_path = test_db
    doc_id_a = str(uuid.uuid4())
    doc_id_b = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id_a, "Alice in Wonderland")
    await _insert_doc(factory, tmp_path, doc_id_b, "The Odyssey")

    citations = [
        {
            "document_title": "Alice in Wonderland",
            "section_heading": "Ch1",
            "page": 1,
            "excerpt": "...",
        },
        {
            "document_title": "The Odyssey",
            "section_heading": "Book I",
            "page": 10,
            "excerpt": "...",
        },
    ]
    result = _make_graph_result(
        answer="Comparison answer.", citations=citations, confidence="medium"
    )
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [e async for e in svc.stream_answer("Compare the two books?", None, "all", None)]

    done_payload = json.loads(events[-1][len("data: "):])
    assert done_payload["done"] is True
    titles = {c["document_title"] for c in done_payload["citations"]}
    assert "Alice in Wonderland" in titles
    assert "The Odyssey" in titles


@pytest.mark.asyncio
async def test_citations_no_title_for_single_scope(test_db):
    """Graph (synthesize_node) already cleared document_title for scope=single."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Physics Textbook")

    citations = [
        {"document_title": None, "section_heading": "Forces", "page": 3, "excerpt": "F=ma"}
    ]
    result = _make_graph_result(
        answer="Force equals mass times acceleration.",
        citations=citations,
        confidence="high",
    )
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [
            e async for e in svc.stream_answer(
                "What is Newton's 2nd law?", [doc_id], "single", None
            )
        ]

    done_payload = json.loads(events[-1][len("data: "):])
    assert done_payload["done"] is True
    assert all(c["document_title"] is None for c in done_payload["citations"])


# ---------------------------------------------------------------------------
# S71 — _should_use_summary unit tests (unchanged)
# ---------------------------------------------------------------------------


def test_should_use_summary_matches_keywords():
    assert _should_use_summary("Can you summarize this document?") is True
    assert _should_use_summary("Give me an overview of the book") is True
    assert _should_use_summary("What are the key points?") is True
    assert _should_use_summary("What is this about?") is True


def test_should_use_summary_no_match():
    assert _should_use_summary("Who is Achilles?") is False
    assert _should_use_summary("What happens in chapter 3?") is False


@pytest.mark.asyncio
async def test_qa_summary_question_routes_via_graph(test_db):
    """Summary-intent question: S77 summary_node stub returns stub answer string."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, title="Iliad")

    result = _make_graph_result(
        answer="[summary_node stub]",
        confidence="high",
        intent="summary",
    )
    mock_graph = _make_mock_graph(result)

    with patch("app.runtime.chat_graph.get_chat_graph", return_value=mock_graph):
        svc = QAService()
        events = [
            e async for e in svc.stream_answer(
                "Can you summarize this document?", [doc_id], "single", None
            )
        ]

    done_payload = json.loads(events[-1][len("data: "):])
    assert done_payload["done"] is True
    assert "summary_node" in done_payload["answer"]
