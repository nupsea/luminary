"""Unit tests for EnrichmentQueueWorker -- S133."""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import DocumentModel, EnrichmentJobModel
from app.services.enrichment_worker import EnrichmentQueueWorker


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


@pytest.mark.asyncio
async def test_worker_transitions_job_to_done(test_db):
    """A pending job should transition to done after the handler runs."""
    engine, factory, tmp_path = test_db

    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test",
                format="pdf",
                content_type="book",
                word_count=100,
                page_count=1,
                file_path="/fake/test.pdf",
                stage="enriching",
            )
        )
        session.add(
            EnrichmentJobModel(
                id=job_id,
                document_id=doc_id,
                job_type="test_type",
                status="pending",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    called: list[str] = []

    async def test_handler(document_id: str, j_id: str) -> None:
        called.append(j_id)

    worker = EnrichmentQueueWorker(poll_interval_s=0.1)
    worker.register("test_type", test_handler)
    await worker._dispatch_pending()
    # Wait for doc task to complete
    await asyncio.sleep(0.3)

    async with factory() as session:
        result = await session.execute(
            select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
        )
        updated_job = result.scalar_one_or_none()

    assert updated_job is not None
    assert updated_job.status == "done"
    assert job_id in called


@pytest.mark.asyncio
async def test_worker_failed_job_sets_error_message(test_db):
    """When a handler raises, job status becomes 'failed' with error_message set."""
    engine, factory, tmp_path = test_db

    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test",
                format="pdf",
                content_type="book",
                word_count=10,
                page_count=1,
                file_path="/fake.pdf",
                stage="enriching",
            )
        )
        session.add(
            EnrichmentJobModel(
                id=job_id,
                document_id=doc_id,
                job_type="fail_type",
                status="pending",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    async def failing_handler(document_id: str, j_id: str) -> None:
        raise RuntimeError("deliberate failure")

    worker = EnrichmentQueueWorker(poll_interval_s=0.1)
    worker.register("fail_type", failing_handler)
    await worker._dispatch_pending()
    await asyncio.sleep(0.3)

    async with factory() as session:
        result = await session.execute(
            select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
        )
        j = result.scalar_one_or_none()

    assert j is not None
    assert j.status == "failed"
    assert "deliberate failure" in (j.error_message or "")


@pytest.mark.asyncio
async def test_worker_skips_already_active_document(test_db):
    """A document already being processed should not spawn a second task."""
    engine, factory, tmp_path = test_db

    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Test",
                format="pdf",
                content_type="book",
                word_count=10,
                page_count=1,
                file_path="/fake.pdf",
                stage="enriching",
            )
        )
        session.add(
            EnrichmentJobModel(
                id=job_id,
                document_id=doc_id,
                job_type="test_type",
                status="pending",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    call_count = [0]

    async def counting_handler(document_id: str, j_id: str) -> None:
        call_count[0] += 1

    worker = EnrichmentQueueWorker(poll_interval_s=0.1)
    worker.register("test_type", counting_handler)

    # Simulate doc already active
    worker._active_doc_ids.add(doc_id)
    await worker._dispatch_pending()
    await asyncio.sleep(0.2)

    # Handler should not have been called since doc was already active
    assert call_count[0] == 0
