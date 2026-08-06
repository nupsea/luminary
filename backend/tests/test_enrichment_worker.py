"""Unit tests for EnrichmentQueueWorker -- S133."""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.enrichment_worker as ew
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import DocumentModel, EnrichmentJobModel
from app.services.enrichment_worker import EnrichmentQueueWorker
from app.services.llm import LLMAPIConnectionError


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
    await worker.stop()

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
    await worker.stop()

    async with factory() as session:
        result = await session.execute(
            select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
        )
        j = result.scalar_one_or_none()

    assert j is not None
    assert j.status == "failed"
    assert "deliberate failure" in (j.error_message or "")


def _seed_job(factory, doc_id, job_id, job_type):
    async def _go():
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
                    job_type=job_type,
                    status="pending",
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()

    return _go()


@pytest.mark.asyncio
async def test_worker_retries_transient_llm_unavailable_then_succeeds(test_db, monkeypatch):
    engine, factory, tmp_path = test_db
    monkeypatch.setattr(ew, "_LLM_RETRY_BASE_DELAY_S", 0.0)
    monkeypatch.setattr(ew, "_LLM_RETRY_MAX_DELAY_S", 0.0)

    doc_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_job(factory, doc_id, job_id, "flaky")

    calls = {"n": 0}

    async def flaky_handler(document_id: str, j_id: str) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise LLMAPIConnectionError(message="busy", llm_provider="ollama", model="gemma4")

    worker = EnrichmentQueueWorker(poll_interval_s=0.1)
    worker.register("flaky", flaky_handler)
    await worker._dispatch_pending()
    await asyncio.sleep(0.5)
    await worker.stop()

    async with factory() as session:
        j = (
            await session.execute(
                select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
            )
        ).scalar_one_or_none()

    assert calls["n"] == 3
    assert j is not None
    assert j.status == "done"


@pytest.mark.asyncio
async def test_worker_exhausts_backoff_then_fails(test_db, monkeypatch):
    engine, factory, tmp_path = test_db
    monkeypatch.setattr(ew, "_LLM_RETRY_BASE_DELAY_S", 0.0)
    monkeypatch.setattr(ew, "_LLM_RETRY_MAX_DELAY_S", 0.0)

    doc_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_job(factory, doc_id, job_id, "down")

    calls = {"n": 0}

    async def always_down(document_id: str, j_id: str) -> None:
        calls["n"] += 1
        raise LLMAPIConnectionError(message="down", llm_provider="ollama", model="gemma4")

    worker = EnrichmentQueueWorker(poll_interval_s=0.1)
    worker.register("down", always_down)
    await worker._dispatch_pending()
    await asyncio.sleep(0.5)
    await worker.stop()

    async with factory() as session:
        j = (
            await session.execute(
                select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
            )
        ).scalar_one_or_none()

    assert calls["n"] == ew._LLM_RETRY_MAX_ATTEMPTS
    assert j is not None
    assert j.status == "failed"
    assert "LLM unavailable" in (j.error_message or "")


def _model_missing(model: str) -> LLMAPIConnectionError:
    """What Ollama returns for an unpulled model: a 404 litellm wraps as a
    connection error, distinguishable from a dead server only by this text."""
    return LLMAPIConnectionError(
        message=f'OllamaException - {{"error":"model \'{model}\' not found"}}',
        llm_provider="ollama",
        model=model,
    )


@pytest.mark.asyncio
async def test_an_uninstalled_model_skips_the_job_rather_than_failing_it(test_db, monkeypatch):
    """The user saw "Enrichment failed" for a capability they never installed."""
    _engine, factory, _tmp = test_db
    monkeypatch.setattr(ew, "_LLM_RETRY_BASE_DELAY_S", 0.0)
    monkeypatch.setattr(ew, "_LLM_RETRY_MAX_DELAY_S", 0.0)

    doc_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_job(factory, doc_id, job_id, "vision")

    calls = {"n": 0}

    async def needs_vision(document_id: str, j_id: str) -> None:
        calls["n"] += 1
        raise _model_missing("qwen2.5vl:7b")

    worker = EnrichmentQueueWorker(poll_interval_s=0.1)
    worker.register("vision", needs_vision)
    await worker._dispatch_pending()
    await asyncio.sleep(0.5)
    await worker.stop()

    async with factory() as session:
        j = (
            await session.execute(
                select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
            )
        ).scalar_one()

    assert j.status == "skipped"
    assert calls["n"] == 1, "a model that is not installed cannot appear during a backoff"
    assert "vision model" in (j.error_message or "").lower()
    assert "qwen2.5vl:7b" in (j.error_message or "")


@pytest.mark.asyncio
async def test_a_missing_model_outside_the_catalogue_still_names_itself(test_db, monkeypatch):
    _engine, factory, _tmp = test_db
    monkeypatch.setattr(ew, "_LLM_RETRY_BASE_DELAY_S", 0.0)
    monkeypatch.setattr(ew, "_LLM_RETRY_MAX_DELAY_S", 0.0)

    doc_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_job(factory, doc_id, job_id, "exotic")

    async def needs_exotic(document_id: str, j_id: str) -> None:
        raise _model_missing("some-model-we-do-not-ship")

    worker = EnrichmentQueueWorker(poll_interval_s=0.1)
    worker.register("exotic", needs_exotic)
    await worker._dispatch_pending()
    await asyncio.sleep(0.5)
    await worker.stop()

    async with factory() as session:
        j = (
            await session.execute(
                select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
            )
        ).scalar_one()

    assert j.status == "skipped"
    assert "some-model-we-do-not-ship" in (j.error_message or "")


@pytest.mark.asyncio
async def test_skipped_jobs_are_requeued_when_a_component_arrives(test_db):
    _engine, factory, _tmp = test_db
    doc_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_job(factory, doc_id, job_id, "vision")

    async with factory() as session:
        job = (
            await session.execute(
                select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
            )
        ).scalar_one()
        job.status = "skipped"
        job.error_message = "Needs the vision model"
        job.completed_at = datetime.now(UTC)
        await session.commit()

    assert await ew.requeue_skipped_jobs() == 1

    async with factory() as session:
        j = (
            await session.execute(
                select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
            )
        ).scalar_one()

    assert j.status == "pending"
    assert j.error_message is None
    assert j.completed_at is None


@pytest.mark.asyncio
async def test_startup_reclaims_skipped_jobs(test_db):
    """A restart is the likeliest moment for a missing component to have arrived."""
    _engine, factory, _tmp = test_db
    doc_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_job(factory, doc_id, job_id, "vision")

    async with factory() as session:
        job = (
            await session.execute(
                select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
            )
        ).scalar_one()
        job.status = "skipped"
        await session.commit()

    worker = EnrichmentQueueWorker(poll_interval_s=60.0)
    await worker.start()
    await worker.stop()

    async with factory() as session:
        j = (
            await session.execute(
                select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
            )
        ).scalar_one()

    assert j.status == "pending"


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
    await worker.stop()

    # Handler should not have been called since doc was already active
    assert call_count[0] == 0


async def _seed_boot_job(factory, *, status: str, attempts: int, doc_id: str = "doc-boot") -> str:
    job_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="t",
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
                job_type="image_analyze",
                status=status,
                attempts=attempts,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()
    return job_id


async def _boot_status_of(factory, job_id: str) -> str:
    async with factory() as session:
        row = (
            await session.execute(
                select(EnrichmentJobModel.status).where(EnrichmentJobModel.id == job_id)
            )
        ).scalar_one()
    return row


@pytest.mark.asyncio
async def test_boot_requeues_failed_job_under_attempt_limit(test_db):
    _engine, factory, _tmp = test_db
    job_id = await _seed_boot_job(factory, status="failed", attempts=ew._MAX_BOOT_ATTEMPTS - 1)

    worker = EnrichmentQueueWorker(poll_interval_s=60)
    await worker.start()
    await worker.stop()

    assert await _boot_status_of(factory, job_id) == "pending"


@pytest.mark.asyncio
async def test_boot_leaves_exhausted_failed_job_alone(test_db):
    """A deterministically-failing job must not re-run its model every launch."""
    _engine, factory, _tmp = test_db
    job_id = await _seed_boot_job(factory, status="failed", attempts=ew._MAX_BOOT_ATTEMPTS)

    worker = EnrichmentQueueWorker(poll_interval_s=60)
    await worker.start()
    await worker.stop()

    assert await _boot_status_of(factory, job_id) == "failed"


@pytest.mark.asyncio
async def test_boot_always_requeues_skipped_regardless_of_attempts(test_db):
    """Skipping costs a refused call, not model work, so it never exhausts retries."""
    _engine, factory, _tmp = test_db
    job_id = await _seed_boot_job(factory, status="skipped", attempts=ew._MAX_BOOT_ATTEMPTS + 5)

    worker = EnrichmentQueueWorker(poll_interval_s=60)
    await worker.start()
    await worker.stop()

    assert await _boot_status_of(factory, job_id) == "pending"
