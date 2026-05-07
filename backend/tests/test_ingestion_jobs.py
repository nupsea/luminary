"""Tests for IngestionJobRegistry and cancel-on-delete in /documents."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel
from app.services.ingestion_jobs import IngestionJobRegistry, get_ingestion_jobs


# ---------------------------------------------------------------------------
# Registry unit tests (no DB, no FastAPI)
# ---------------------------------------------------------------------------


async def _sleep_forever() -> None:
    await asyncio.Event().wait()


async def _quick_return() -> None:
    await asyncio.sleep(0)


async def test_launch_registers_task_and_clears_on_completion():
    reg = IngestionJobRegistry()
    doc_id = "doc-1"
    task = reg.launch(doc_id, _quick_return())
    assert reg.get(doc_id) is task
    assert reg.is_running(doc_id) is True
    await task
    # Done callbacks run on the event loop; yield once so they fire.
    await asyncio.sleep(0)
    assert reg.get(doc_id) is None
    assert reg.is_running(doc_id) is False


async def test_double_launch_reuses_running_task():
    reg = IngestionJobRegistry()
    doc_id = "doc-2"
    first = reg.launch(doc_id, _sleep_forever())
    second = reg.launch(doc_id, _sleep_forever())
    try:
        assert first is second
        assert reg.is_running(doc_id) is True
    finally:
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)


async def test_cancel_running_task_returns_true_and_clears_entry():
    reg = IngestionJobRegistry()
    doc_id = "doc-3"
    reg.launch(doc_id, _sleep_forever())
    cancelled = await reg.cancel(doc_id)
    assert cancelled is True
    assert reg.is_running(doc_id) is False
    assert reg.get(doc_id) is None


async def test_cancel_unknown_document_returns_false():
    reg = IngestionJobRegistry()
    assert await reg.cancel("nonexistent") is False


async def test_cancel_already_done_task_returns_false():
    reg = IngestionJobRegistry()
    doc_id = "doc-4"
    task = reg.launch(doc_id, _quick_return())
    await task
    await asyncio.sleep(0)  # let done callback run
    assert await reg.cancel(doc_id) is False


async def test_cancel_propagates_through_finally_blocks():
    """A workflow that catches `Exception` must still surface CancelledError."""
    reg = IngestionJobRegistry()
    doc_id = "doc-5"
    cleanup_ran = asyncio.Event()

    async def workflow() -> None:
        try:
            await asyncio.Event().wait()
        except Exception:  # the kind of catch the real workflow has
            cleanup_ran.set()
            raise
        finally:
            cleanup_ran.set()

    reg.launch(doc_id, workflow())
    # Yield once so the task is actually started before we cancel.
    await asyncio.sleep(0)
    cancelled = await reg.cancel(doc_id)
    assert cancelled is True
    assert cleanup_ran.is_set()


# ---------------------------------------------------------------------------
# delete_document integration: cancel-before-teardown
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


@pytest.fixture(autouse=True)
async def _reset_ingestion_registry():
    """Each test starts with a clean registry."""
    get_ingestion_jobs().reset()
    yield
    get_ingestion_jobs().reset()


async def test_delete_cancels_in_flight_ingestion(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    file_path = tmp_path / f"{doc_id}.txt"
    file_path.write_text("placeholder")

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="In-progress doc",
                format="txt",
                content_type="notes",
                word_count=0,
                page_count=0,
                file_path=str(file_path),
                stage="embedding",
            )
        )
        await session.commit()

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def fake_ingestion() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    get_ingestion_jobs().launch(doc_id, fake_ingestion())
    # Yield so the fake task hits its first await before we delete.
    await started.wait()
    assert get_ingestion_jobs().is_running(doc_id) is True

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(f"/documents/{doc_id}")
    assert resp.status_code == 204

    assert cancelled.is_set(), "ingestion task should have received CancelledError"
    assert get_ingestion_jobs().is_running(doc_id) is False

    async with factory() as session:
        result = await session.execute(
            select(DocumentModel).where(DocumentModel.id == doc_id)
        )
        assert result.scalar_one_or_none() is None


async def test_delete_without_running_ingestion_still_succeeds(test_db):
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    file_path = tmp_path / f"{doc_id}.txt"
    file_path.write_text("placeholder")

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Idle doc",
                format="txt",
                content_type="notes",
                word_count=10,
                page_count=1,
                file_path=str(file_path),
                stage="complete",
            )
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(f"/documents/{doc_id}")
    assert resp.status_code == 204

    async with factory() as session:
        result = await session.execute(
            select(DocumentModel).where(DocumentModel.id == doc_id)
        )
        assert result.scalar_one_or_none() is None
