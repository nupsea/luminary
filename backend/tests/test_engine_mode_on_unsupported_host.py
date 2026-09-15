"""The mode a user chose is kept, and what it cannot run on this host is said, not swallowed.

On a host `local_inference_support` refuses, every local model call is refused.
Background callers catch every failure as non-fatal, so Hybrid mode left each
document without summaries, tags or titles while it read as complete, and the
routing table reported that work as running on this machine.
"""

import re
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
from app.exceptions import LocalInferenceRefused
from app.host_support import HostSupport
from app.models import DocumentModel, EnrichmentJobModel

UNSUPPORTED = HostSupport(False, "no_accelerator", "Linux/x86_64", "no local models here")
SUPPORTED = HostSupport(True, None, "Darwin/arm64", None)


def _host(verdict: HostSupport):
    return patch("app.host_support.local_inference_support", return_value=verdict)


@pytest.fixture
def mode():
    """Set llm_mode with a usable key, restoring the module cache afterwards."""
    from app.services import settings_service as ss

    original = dict(ss._cache)

    def _set(value: str) -> None:
        ss._cache.update(
            {
                "llm_mode": value,
                "cloud_provider": "openai",
                "cloud_model": "gpt-4o-mini",
                "openai_api_key": "sk-x",
            }
        )

    yield _set
    ss._cache.clear()
    ss._cache.update(original)


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    yield factory
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    get_settings.cache_clear()
    await engine.dispose()


# What each mode runs on a refusing host


@pytest.mark.parametrize(
    ("value", "not_run"),
    [
        ("private", {"enrichment", "figures", "study_material", "answering"}),
        ("hybrid", {"enrichment", "figures"}),
        # The figure reader is local in every mode.
        ("cloud", {"figures"}),
    ],
)
def test_the_routing_table_names_the_work_this_host_does_not_run(mode, value, not_run):
    from app.services.llm_routing import routing_report

    mode(value)
    with (
        _host(UNSUPPORTED),
        patch("app.model_registry.configured_generation_override", return_value=None),
    ):
        report = routing_report()
    assert {w.id for w in report.work if w.refused_reason} == not_run
    # A refused row is never reported as leaving: nothing is sent for work that does not run.
    assert not {w.id for w in report.work if w.refused_reason} & set(report.leaves_device)


def test_a_supported_host_runs_everything_its_mode_names(mode):
    from app.services.llm_routing import routing_report

    mode("private")
    with _host(SUPPORTED):
        report = routing_report()
    assert [w.id for w in report.work if w.refused_reason] == []


@pytest.mark.parametrize("value", ["private", "hybrid", "cloud"])
@pytest.mark.parametrize("verdict", [SUPPORTED, UNSUPPORTED])
def test_the_prediction_agrees_with_the_call_it_predicts(mode, value, verdict):
    """`refusal` is asked instead of attempting the call, so the two may never disagree."""
    from app.services.llm import LLMService
    from app.services.llm_routing import refusal

    mode(value)
    with _host(verdict):
        predicted = refusal("background") is not None
        try:
            LLMService()._resolve_model(None, background=True)
            refused = False
        except LocalInferenceRefused:
            refused = True
    assert predicted is refused


# Background work records the refusal instead of failing or finishing empty


async def _seed_job(factory, job_type: str) -> tuple[str, str]:
    doc_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Doc",
                format="pdf",
                content_type="book",
                word_count=100,
                page_count=1,
                file_path="/fake/doc.pdf",
                stage="enriching",
            )
        )
        session.add(
            EnrichmentJobModel(id=job_id, document_id=doc_id, job_type=job_type, status="pending")
        )
        await session.commit()
    return doc_id, job_id


async def test_a_job_whose_model_is_refused_is_skipped_without_running(test_db, mode):
    from app.services.enrichment_worker import EnrichmentQueueWorker
    from app.services.llm_routing import NOT_RUN_ON_THIS_HOST

    doc_id, job_id = await _seed_job(test_db, "concept_link")
    handler = AsyncMock()
    worker = EnrichmentQueueWorker(poll_interval_s=0.1)
    worker.register("concept_link", handler)

    mode("hybrid")
    with _host(UNSUPPORTED):
        await worker._run_job(job_id, doc_id, "concept_link")

    handler.assert_not_awaited()
    async with test_db() as session:
        stmt = select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
        job = (await session.execute(stmt)).scalar_one()
    assert job.status == "skipped"
    assert job.error_message == NOT_RUN_ON_THIS_HOST
    # No work was done, so no attempt is spent.
    assert (job.attempts or 0) == 0


async def test_a_job_that_calls_no_model_still_runs_on_a_refusing_host(test_db, mode):
    from app.services.enrichment_worker import EnrichmentQueueWorker

    doc_id, job_id = await _seed_job(test_db, "image_extract")
    handler = AsyncMock()
    worker = EnrichmentQueueWorker(poll_interval_s=0.1)
    worker.register("image_extract", handler)

    mode("private")
    with _host(UNSUPPORTED):
        await worker._run_job(job_id, doc_id, "image_extract")

    handler.assert_awaited_once()


async def test_a_refusal_raised_inside_a_handler_is_a_skip_not_a_failure(test_db, mode):
    from app.services.enrichment_worker import EnrichmentQueueWorker

    doc_id, job_id = await _seed_job(test_db, "unclassified_for_this_test")
    worker = EnrichmentQueueWorker(poll_interval_s=0.1)
    worker.register(
        "unclassified_for_this_test", AsyncMock(side_effect=LocalInferenceRefused("refused here"))
    )

    mode("private")
    await worker._run_job(job_id, doc_id, "unclassified_for_this_test")

    async with test_db() as session:
        stmt = select(EnrichmentJobModel).where(EnrichmentJobModel.id == job_id)
        job = (await session.execute(stmt)).scalar_one()
    assert job.status == "skipped"
    assert job.error_message == "refused here"
    assert job.attempts == 0


def test_every_registered_job_declares_its_model():
    """A new job type must say which model it calls, or a refusing host fails it silently."""
    from app.services.enrichment_worker import JOB_MODEL_ROLE, JOBS_WITHOUT_A_MODEL

    main_source = (Path(__file__).parent.parent / "app" / "main.py").read_text(encoding="utf-8")
    registered = set(re.findall(r'_worker\.register\("([a-z_]+)"', main_source))
    assert registered, "no registrations found; the pattern no longer matches main.py"
    assert registered == set(JOB_MODEL_ROLE) | JOBS_WITHOUT_A_MODEL


async def test_ingest_does_not_attempt_summaries_the_host_refuses(mode):
    from app.workflows.ingestion_nodes import finalize

    service = MagicMock()
    service.generate_all_summaries = AsyncMock()
    service.refresh_library_summary = AsyncMock()
    mode("hybrid")
    with (
        _host(UNSUPPORTED),
        patch.object(finalize, "get_summarization_service", return_value=service),
    ):
        await finalize._run_pregenerate("doc-1")
    service.generate_all_summaries.assert_not_awaited()

    with (
        _host(SUPPORTED),
        patch.object(finalize, "get_summarization_service", return_value=service),
    ):
        await finalize._run_pregenerate("doc-1")
    service.generate_all_summaries.assert_awaited_once()


async def test_the_summary_repair_does_nothing_while_refused(mode):
    from app.services import section_summarizer

    mode("hybrid")
    with (
        _host(UNSUPPORTED),
        patch.object(
            section_summarizer, "get_session_factory", side_effect=AssertionError("queried")
        ),
    ):
        assert await section_summarizer.resummarize_documents_missing_summaries() == 0


def test_a_private_mode_error_names_the_host_not_ollama(mode):
    from app.services.settings_service import get_llm_error_message

    mode("private")
    with _host(UNSUPPORTED):
        assert get_llm_error_message() == "no local models here"
    with _host(SUPPORTED):
        assert "ollama serve" in get_llm_error_message()


# Changing the one setting


async def test_an_unknown_mode_is_refused(test_db):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/settings/llm", json={"mode": "turbo"})
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("verdict", "before", "after", "resumes"),
    [
        # The refusal is lifted: skipped jobs and missing summaries are owed.
        (UNSUPPORTED, "hybrid", "cloud", True),
        # Still refused: nothing to resume.
        (UNSUPPORTED, "private", "hybrid", False),
        # Nothing was refused: a mode change must not start a library-wide pass.
        (SUPPORTED, "hybrid", "cloud", False),
    ],
)
async def test_work_resumes_only_when_a_mode_change_lifts_the_refusal(
    test_db, mode, verdict, before, after, resumes
):
    from app.main import app
    from app.routers import settings as settings_router

    mode(before)
    requeue = AsyncMock(return_value=0)
    repair = AsyncMock(return_value=0)
    with (
        _host(verdict),
        patch("app.services.enrichment_worker.requeue_skipped_jobs", requeue),
        patch("app.services.section_summarizer.resummarize_documents_missing_summaries", repair),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/settings/llm", json={"mode": after})
        for task in list(settings_router._background_tasks):
            await task

    assert resp.status_code == 200
    assert resp.json()["mode"] == after
    assert requeue.await_count == (1 if resumes else 0)
    assert repair.await_count == (1 if resumes else 0)
