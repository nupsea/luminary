"""Tests for QAService and POST /qa endpoint."""

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


async def _async_iter(items):
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# _split_response — unit tests
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
    citations: list[dict] = []
    full_text = "Partial answer." + json.dumps({"citations": citations, "confidence": "medium"})
    _, _, confidence = _split_response(full_text)
    assert confidence == "medium"


def test_split_response_malformed_json_returns_empty_citations():
    full_text = 'Answer text.{"citations": [invalid json'
    answer, citations, confidence = _split_response(full_text)
    assert citations == []
    assert confidence == "low"


def test_split_response_strips_json_label_line():
    """LLM echoes 'JSON:' label before the JSON block — should be stripped."""
    citations = [{"document_title": "Bio", "section_heading": "Cells", "page": 1, "excerpt": "..."}]
    full_text = "The cell is the basic unit of life.\nJSON:\n" + json.dumps(
        {"citations": citations, "confidence": "high"}
    )
    answer, _, _ = _split_response(full_text)
    assert answer == "The cell is the basic unit of life."


def test_split_response_strips_instruction_echo():
    """LLM echoes the system prompt fragment as a label — should be stripped."""
    citations: list[dict] = []
    # Simulate mistral echoing the old system prompt instruction text
    full_text = (
        "ONLY JSON (no prose inside the JSON, do not repeat the answer):\n"
        + json.dumps({"citations": citations, "confidence": "medium"})
    )
    answer, _, _ = _split_response(full_text)
    assert answer == ""


def test_split_response_strips_here_is_json_label():
    """'Here is a JSON response:' label is stripped."""
    citations: list[dict] = []
    full_text = "Alice explores Wonderland.\nHere is a JSON response:\n" + json.dumps(
        {"citations": citations, "confidence": "high"}
    )
    answer, _, _ = _split_response(full_text)
    assert answer == "Alice explores Wonderland."


def test_split_response_style_b_answer_in_json():
    """Style B: LLM puts answer inside the JSON object."""
    citations = [{"document_title": "Gita", "section_heading": "Ch1", "page": 1, "excerpt": "..."}]
    full_text = json.dumps(
        {"answer": "Arjuna questions his duty.", "citations": citations, "confidence": "medium"}
    )
    answer, parsed_citations, confidence = _split_response(full_text)
    assert answer == "Arjuna questions his duty."
    assert len(parsed_citations) == 1
    assert confidence == "medium"


def test_split_response_prose_with_colon_not_stripped():
    """A prose line ending with a colon but no 'json' word is kept intact."""
    citations: list[dict] = []
    # "The main themes are:" is legitimate prose — it should NOT be stripped
    full_text = "The main themes are:\n- Adventure\n- Mystery.\n" + json.dumps(
        {"citations": citations, "confidence": "medium"}
    )
    answer, _, _ = _split_response(full_text)
    assert "main themes" in answer


# ---------------------------------------------------------------------------
# _build_context — unit tests
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
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_yields_token_events_for_answer(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Biology Book")

    citations = [
        {"document_title": "Biology Book", "section_heading": "Cells", "page": 1, "excerpt": "..."}
    ]
    llm_response = "Mitochondria produces ATP." + json.dumps(
        {"citations": citations, "confidence": "high"}
    )

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[_make_chunk(doc_id)])

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_async_iter([llm_response]))

    with (
        patch("app.services.qa.get_retriever", return_value=mock_retriever),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
        svc = QAService()
        events = [
            e async for e in svc.stream_answer(
                "What does mitochondria do?", [doc_id], "single", None
            )
        ]

    # Token events + done event
    assert len(events) >= 2
    token_events = [e for e in events if '"token"' in e]
    assert len(token_events) > 0

    # All token events have correct format
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
        {"document_title": "Physics", "section_heading": "Forces", "page": 5, "excerpt": "F=ma"}
    ]
    llm_response = "Force equals mass times acceleration." + json.dumps(
        {"citations": citations, "confidence": "high"}
    )

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[_make_chunk(doc_id)])

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_async_iter([llm_response]))

    with (
        patch("app.services.qa.get_retriever", return_value=mock_retriever),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
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
    # scope='single' → document_title is cleared to None (redundant for single doc)
    assert done_payload["citations"][0]["document_title"] is None
    assert "qa_id" in done_payload


@pytest.mark.asyncio
async def test_stream_stores_qa_in_database(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "History")

    llm_response = "Napoleon was French." + json.dumps({"citations": [], "confidence": "medium"})

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[_make_chunk(doc_id)])

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_async_iter([llm_response]))

    with (
        patch("app.services.qa.get_retriever", return_value=mock_retriever),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
        svc = QAService()
        events = [e async for e in svc.stream_answer("Who was Napoleon?", [doc_id], "single", None)]

    done_payload = json.loads(events[-1][len("data: "):])
    qa_id = done_payload["qa_id"]

    async with factory() as session:
        result = await session.execute(select(QAHistoryModel).where(QAHistoryModel.id == qa_id))
        stored = result.scalar_one_or_none()

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
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id)

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[_make_chunk(doc_id)])

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_async_iter([NOT_FOUND_SENTINEL]))

    with (
        patch("app.services.qa.get_retriever", return_value=mock_retriever),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
        svc = QAService()
        events = [e async for e in svc.stream_answer("Unknown question?", None, "all", None)]

    # Only one event — the not_found done event
    assert len(events) == 1
    payload = json.loads(events[0][len("data: "):])
    assert payload["done"] is True
    assert payload["not_found"] is True


@pytest.mark.asyncio
async def test_not_found_no_token_events(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id)

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[])

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_async_iter([NOT_FOUND_SENTINEL]))

    with (
        patch("app.services.qa.get_retriever", return_value=mock_retriever),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
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

    llm_response = "The answer is 42." + json.dumps({"citations": [], "confidence": "high"})

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[_make_chunk(doc_id)])

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_async_iter([llm_response]))

    with (
        patch("app.services.qa.get_retriever", return_value=mock_retriever),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/qa", json={"question": "What is the answer?"})

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_endpoint_not_found_response(test_db):
    """Retriever returns [] → no-context guard fires before LLM; endpoint returns error event."""
    _engine, factory, tmp_path = test_db

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[])

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_async_iter([NOT_FOUND_SENTINEL]))

    with (
        patch("app.services.qa.get_retriever", return_value=mock_retriever),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/qa", json={"question": "Impossible question?"})

    assert resp.status_code == 200
    events = [line for line in resp.text.splitlines() if line.startswith("data: ")]
    assert len(events) == 1
    payload = json.loads(events[0][len("data: "):])
    # no-context guard fires before LLM is called when retriever returns []
    assert payload["error"] == "no_context"
    assert payload["done"] is True


@pytest.mark.asyncio
async def test_endpoint_all_scope_passes_none_doc_ids(test_db):
    _engine, factory, tmp_path = test_db

    captured_doc_ids: list = []

    async def fake_retrieve(query, document_ids, k):
        captured_doc_ids.append(document_ids)
        return []

    mock_retriever = MagicMock()
    mock_retriever.retrieve = fake_retrieve

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_async_iter([NOT_FOUND_SENTINEL]))

    with (
        patch("app.services.qa.get_retriever", return_value=mock_retriever),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post(
                "/qa",
                json={"question": "Any question?", "scope": "all", "document_ids": ["doc-1"]},
            )

    # scope=all overrides document_ids → passes None to retriever
    assert captured_doc_ids[0] is None


# ---------------------------------------------------------------------------
# QAService.stream_answer — error flows (S48)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qa_no_context(test_db):
    """Retriever returns 0 chunks → exactly 1 SSE event with error='no_context'."""
    _engine, factory, tmp_path = test_db

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[])

    mock_llm = MagicMock()

    with (
        patch("app.services.qa.get_retriever", return_value=mock_retriever),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
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
    """LLM generate raises → exactly 1 SSE event with error='llm_unavailable'."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id)

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[_make_chunk(doc_id)])

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=Exception("connection refused"))

    with (
        patch("app.services.qa.get_retriever", return_value=mock_retriever),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
        svc = QAService()
        events = [
            e async for e in svc.stream_answer("What is this about?", [doc_id], "single", None)
        ]

    data_lines = [e for e in events if e.startswith("data: ")]
    assert len(data_lines) == 1
    payload = json.loads(data_lines[0][len("data: "):])
    assert payload["error"] == "llm_unavailable"
    assert payload["done"] is True


@pytest.mark.asyncio
async def test_qa_with_mock_llm(test_db):
    """Happy-path: mock LLM returns answer + citations → token events + done event."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Time Machine")

    citations = [
        {
            "document_title": "Time Machine",
            "section_heading": "Chapter 1",
            "page": 3,
            "excerpt": "...",
        }
    ]
    llm_response = "The Time Traveller invented a machine." + json.dumps(
        {"citations": citations, "confidence": "high"}
    )

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(
        return_value=[_make_chunk(doc_id, text="time machine text")]
    )

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_async_iter([llm_response]))

    with (
        patch("app.services.qa.get_retriever", return_value=mock_retriever),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
    ):
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
# S61 — document attribution: _enrich_citation_titles and stream_answer
# ---------------------------------------------------------------------------


def test_enrich_citation_titles_single_scope_clears_title():
    """scope='single' → document_title set to None on all citations."""
    chunk = _make_chunk("doc-a", section="Intro")
    citations = [{"document_title": "Some Book", "section_heading": "Intro", "page": 1}]
    result = _enrich_citation_titles(citations, [chunk], {"doc-a": "Some Book"}, "single")
    assert result[0]["document_title"] is None


def test_enrich_citation_titles_all_scope_populates_from_chunks():
    """scope='all' → document_title populated from matched chunk's doc title."""
    chunk = _make_chunk("doc-b", section="Chapter 2")
    chunk.page = 5
    citations = [{"document_title": "", "section_heading": "Chapter 2", "page": 5}]
    result = _enrich_citation_titles(citations, [chunk], {"doc-b": "The Odyssey"}, "all")
    assert result[0]["document_title"] == "The Odyssey"


@pytest.mark.asyncio
async def test_citations_include_document_title_for_all_scope(test_db):
    """scope='all' with 2 doc chunks → citations carry document_title from DB."""
    _engine, factory, tmp_path = test_db
    doc_id_a = str(uuid.uuid4())
    doc_id_b = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id_a, "Alice in Wonderland")
    await _insert_doc(factory, tmp_path, doc_id_b, "The Odyssey")

    chunk_a = _make_chunk(doc_id_a, section="Chapter 1")
    chunk_a.page = 1
    chunk_b = _make_chunk(doc_id_b, section="Book I")
    chunk_b.page = 10

    citations_json = [
        {"document_title": "", "section_heading": "Chapter 1", "page": 1, "excerpt": "..."},
        {"document_title": "", "section_heading": "Book I", "page": 10, "excerpt": "..."},
    ]
    llm_response = "Comparison answer." + json.dumps(
        {"citations": citations_json, "confidence": "medium"}
    )

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[chunk_a, chunk_b])

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_async_iter([llm_response]))

    with (
        patch("app.services.qa.get_retriever", return_value=mock_retriever),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
        patch("app.services.qa.get_graph_service"),  # suppress real Kuzu
    ):
        svc = QAService()
        events = [
            e async for e in svc.stream_answer("Compare the two books?", None, "all", None)
        ]

    done_payload = json.loads(events[-1][len("data: "):])
    assert done_payload["done"] is True
    titles = {c["document_title"] for c in done_payload["citations"]}
    assert "Alice in Wonderland" in titles
    assert "The Odyssey" in titles


@pytest.mark.asyncio
async def test_citations_no_title_for_single_scope(test_db):
    """scope='single' → document_title=None on all citations."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Physics Textbook")

    citations_json = [
        {
            "document_title": "Physics Textbook",
            "section_heading": "Forces",
            "page": 3,
            "excerpt": "F=ma",
        }
    ]
    llm_response = "Force equals mass times acceleration." + json.dumps(
        {"citations": citations_json, "confidence": "high"}
    )

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[_make_chunk(doc_id, section="Forces")])

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_async_iter([llm_response]))

    with (
        patch("app.services.qa.get_retriever", return_value=mock_retriever),
        patch("app.services.qa.get_llm_service", return_value=mock_llm),
        patch("app.services.qa.get_graph_service"),  # suppress real Kuzu
    ):
        svc = QAService()
        events = [
            e async for e in svc.stream_answer(
                "What is Newton's 2nd law?", [doc_id], "single", None
            )
        ]

    done_payload = json.loads(events[-1][len("data: "):])
    assert done_payload["done"] is True
    assert all(c["document_title"] is None for c in done_payload["citations"])
