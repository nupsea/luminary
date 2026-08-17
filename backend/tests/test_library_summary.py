"""Tests for S55 — cross-document holistic summary (POST /summarize/all).

All tests use an in-memory SQLite DB and mock the LLM service so no model
downloads or live databases are required.
"""

import asyncio
import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, LibrarySummaryModel, SummaryModel

# Shared helpers


async def _async_iter(items):
    for item in items:
        yield item


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


async def _insert_doc(factory, tmp_path: Path, doc_id: str, title: str) -> None:
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title=title,
                format="txt",
                content_type="notes",
                word_count=100,
                page_count=1,
                file_path=str(tmp_path / f"{doc_id}.txt"),
                stage="complete",
            )
        )
        await session.commit()


async def _insert_executive_summary(factory, doc_id: str, content: str) -> None:
    async with factory() as session:
        session.add(
            SummaryModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                mode="executive",
                content=content,
            )
        )
        await session.commit()


def _parse_sse_events(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[len("data: ") :]))
            except json.JSONDecodeError:
                pass
    return events


# Tests


@pytest.mark.asyncio
async def test_library_summary_synthesizes_multiple_docs(test_db):
    """2 docs with executive summaries → POST /summarize/all returns token + done events."""
    _engine, factory, tmp_path = test_db

    doc_id_a = str(uuid.uuid4())
    doc_id_b = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id_a, "Alpha Book")
    await _insert_doc(factory, tmp_path, doc_id_b, "Beta Notes")
    await _insert_executive_summary(factory, doc_id_a, "Alpha covers topic X in depth.")
    await _insert_executive_summary(factory, doc_id_b, "Beta explores topic Y extensively.")

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_async_iter(["Theme A ", "Theme B"]))

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/summarize/all", json={"mode": "executive", "model": None})

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    events = _parse_sse_events(resp.text)
    token_events = [e for e in events if "token" in e]
    done_events = [e for e in events if e.get("done") is True]

    assert len(token_events) >= 1
    assert len(done_events) == 1
    assert done_events[0].get("cached") is False
    assert "summary_id" in done_events[0]


@pytest.mark.asyncio
async def test_library_summary_cached_on_second_call(test_db):
    """Second call returns cached=true in done event without calling the LLM again."""
    _engine, factory, tmp_path = test_db

    doc_id_a = str(uuid.uuid4())
    doc_id_b = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id_a, "Doc A")
    await _insert_doc(factory, tmp_path, doc_id_b, "Doc B")
    await _insert_executive_summary(factory, doc_id_a, "Summary of A.")
    await _insert_executive_summary(factory, doc_id_b, "Summary of B.")

    call_count = 0

    async def _counting_gen(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        yield "Library overview text"

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=_counting_gen)

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # First call — generates and stores
            resp1 = await ac.post("/summarize/all", json={"mode": "executive", "model": None})
            # Second call — should hit cache
            resp2 = await ac.post("/summarize/all", json={"mode": "executive", "model": None})

    assert resp1.status_code == 200
    assert resp2.status_code == 200

    events2 = _parse_sse_events(resp2.text)
    done_events = [e for e in events2 if e.get("done") is True]
    assert len(done_events) == 1
    assert done_events[0].get("cached") is True
    # LLM was called exactly once (first request); second hit cache
    assert call_count == 1


@pytest.mark.asyncio
async def test_library_summary_error_when_fewer_than_2_docs(test_db):
    """Exactly 1 doc with executive summary → serves single doc summary directly."""
    _engine, factory, tmp_path = test_db

    doc_id = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id, "Only Doc")
    await _insert_executive_summary(factory, doc_id, "Only one summary here.")

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock()  # should not be called

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/summarize/all", json={"mode": "executive", "model": None})

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    token_events = [e for e in events if "token" in e]
    done_events = [e for e in events if e.get("done") is True]

    assert len(token_events) == 1
    assert token_events[0]["token"] == "Only one summary here."
    assert len(done_events) == 1
    assert done_events[0].get("cached") is False
    assert "summary_id" in done_events[0]
    mock_llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_library_summary_stays_readable_while_it_refreshes(test_db):
    """A new ingest refreshes the library summary without ever leaving it missing.

    Deleting every row instead left a window with no library summary at all, and
    the next question was what regenerated it: `summary_node` found nothing, fired
    the generation and then queued behind it on the one serving slot -- 54.5s to
    first token against a 13.5s median on 2026-08-17, and answered from retrieval
    rather than from the summary, so it differed in kind too. A reader must see the
    previous summary for the whole time the replacement is being generated, and the
    generation must be background work so an Ask outranks it.
    """
    _engine, factory, tmp_path = test_db

    doc_id_a = str(uuid.uuid4())
    doc_id_b = str(uuid.uuid4())
    await _insert_doc(factory, tmp_path, doc_id_a, "Doc A")
    await _insert_doc(factory, tmp_path, doc_id_b, "Doc B")
    await _insert_executive_summary(factory, doc_id_a, "Summary A.")
    await _insert_executive_summary(factory, doc_id_b, "Summary B.")

    async with factory() as session:
        session.add(
            LibrarySummaryModel(
                id=str(uuid.uuid4()),
                mode="executive",
                content="Cached overview text",
            )
        )
        await session.commit()

    from app.services.summarizer import get_summarization_service

    svc = get_summarization_service()
    generating = asyncio.Event()
    may_finish = asyncio.Event()

    async def _blocked_tokens():
        generating.set()
        await may_finish.wait()
        yield "Fresh overview"

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_blocked_tokens())

    with patch("app.services.summarizer.get_llm_service", return_value=mock_llm):
        refresh = asyncio.create_task(svc.refresh_library_summary())
        await asyncio.wait_for(generating.wait(), timeout=5)

        # Mid-refresh: the previous summary is still what a reader gets.
        during = await svc._fetch_library_cached("executive")
        assert during is not None, "the library summary must never be missing"
        assert during.content == "Cached overview text"

        may_finish.set()
        await asyncio.wait_for(refresh, timeout=5)

    after = await svc._fetch_library_cached("executive")
    assert after is not None
    assert after.content == "Fresh overview", "the refreshed summary must win once stored"

    assert mock_llm.generate.await_args.kwargs["background"] is True, (
        "a refresh nobody is waiting on must not outrank an Ask"
    )
