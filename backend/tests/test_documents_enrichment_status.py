"""`enrichment_status` on GET /documents is the document's state, not one job's.

It used to report a single job -- image_analyze, else image_extract, else
whichever was newest. Six job types are registered, so a document whose image
work had finished reported "done" while its concept_link was still queued: the
library card read "Analysis complete" while the enrichment queue was still
counting the task, and the two surfaces contradicted each other on screen.
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, EnrichmentJobModel


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


async def _seed(factory, jobs: list[tuple[str, str]]) -> str:
    """One document with the given (job_type, status) pairs."""
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(
            DocumentModel(
                id=doc_id,
                title="Doc",
                format="pdf",
                content_type="book",
                word_count=10,
                page_count=1,
                file_path="/tmp/x.pdf",
                stage="complete",
                created_at=datetime.now(UTC),
            )
        )
        for job_type, status in jobs:
            s.add(
                EnrichmentJobModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    job_type=job_type,
                    status=status,
                )
            )
        await s.commit()
    return doc_id


async def _status(doc_id: str) -> str | None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/documents")).json()
    item = next(d for d in body["items"] if d["id"] == doc_id)
    return item["enrichment_status"]


@pytest.mark.anyio
async def test_outstanding_work_outranks_a_finished_image_job(test_db):
    """The regression this exists for: image work done, other work still queued.

    The old query sorted image_analyze first and took one row, so this document
    reported "done" while a task of its own was still pending.
    """
    doc_id = await _seed(
        test_db, [("image_analyze", "done"), ("image_extract", "done"), ("concept_link", "pending")]
    )

    assert await _status(doc_id) == "running"


@pytest.mark.anyio
async def test_a_running_job_reports_running(test_db):
    doc_id = await _seed(test_db, [("image_extract", "done"), ("web_refs", "running")])

    assert await _status(doc_id) == "running"


@pytest.mark.anyio
async def test_a_failure_outranks_the_jobs_that_succeeded(test_db):
    doc_id = await _seed(test_db, [("image_analyze", "done"), ("concept_link", "failed")])

    assert await _status(doc_id) == "failed"


@pytest.mark.anyio
async def test_a_skip_is_not_hidden_behind_done(test_db):
    """`skipped` means a model the user never installed, so it is actionable.

    Reporting "done" for the document would bury the one thing they could fix.
    """
    doc_id = await _seed(test_db, [("concept_link", "done"), ("image_analyze", "skipped")])

    assert await _status(doc_id) == "skipped"


@pytest.mark.anyio
async def test_all_done_reports_done(test_db):
    doc_id = await _seed(
        test_db, [("image_extract", "done"), ("image_analyze", "done"), ("concept_link", "done")]
    )

    assert await _status(doc_id) == "done"


@pytest.mark.anyio
async def test_a_document_with_no_jobs_reports_nothing(test_db):
    """No jobs is not a state to render; the card shows no badge at all."""
    doc_id = await _seed(test_db, [])

    assert await _status(doc_id) is None
