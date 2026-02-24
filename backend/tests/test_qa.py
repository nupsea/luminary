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
    assert done_payload["citations"][0]["document_title"] == "Physics"
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
    assert payload["not_found"] is True


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
