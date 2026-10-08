"""Tests for IngestionJobRegistry and cancel-on-delete in /documents."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import DocumentModel, FlashcardModel, SectionModel
from app.services.ingestion_jobs import IngestionJobRegistry, get_ingestion_jobs

# Registry unit tests (no DB, no FastAPI)


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


# delete_document integration: cancel-before-teardown


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
        result = await session.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        assert result.scalar_one_or_none() is None


async def test_delete_cancels_card_generation_for_uncovered_sections(test_db):
    """#242: fill-uncovered outlived the delete and wrote cards for a document that was gone."""
    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Doc",
                format="txt",
                content_type="notes",
                file_path=str(tmp_path / "doc.txt"),
                stage="complete",
            )
        )
        session.add(
            SectionModel(id="sec", document_id=doc_id, heading="One", level=1, section_order=0)
        )
        await session.commit()

    started = asyncio.Event()
    release = asyncio.Event()
    cancelled = asyncio.Event()

    async def generate(*, document_id, session, **_kwargs):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        card = FlashcardModel(
            id=str(uuid.uuid4()),
            document_id=document_id,
            question="Q",
            answer="A",
            source_excerpt="",
        )
        session.add(card)
        await session.commit()
        return [card]

    svc = MagicMock(generate=generate)
    transport = ASGITransport(app=app)
    with patch("app.services.flashcard.get_flashcard_service", return_value=svc):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/flashcards/health/{doc_id}/fill-uncovered", json={"section_ids": ["sec"]}
            )
            assert resp.status_code == 202
            await started.wait()
            resp = await client.delete(f"/documents/{doc_id}")
            assert resp.status_code == 204
        release.set()
        await asyncio.sleep(0.1)

    # The cancel, not only the foreign key: an uncancelled task spends model time per section.
    assert cancelled.is_set()
    async with factory() as session:
        cards = (await session.execute(select(FlashcardModel))).scalars().all()
    assert cards == []


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
        result = await session.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        assert result.scalar_one_or_none() is None
