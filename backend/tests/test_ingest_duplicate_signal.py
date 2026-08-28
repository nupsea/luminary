"""A re-upload of a document we already hold must not be reported as work.

Ingestion dedupes on file hash. When the existing copy is already `complete`,
nothing will run -- but the endpoint used to answer "processing", so the client
tracked a document that would never move and the user saw an upload that
appeared to do nothing at all. `status` now distinguishes the two.

The stages that DO start work keep saying "processing": `error` relaunches
ingestion on the same row, and an in-progress duplicate has a real job behind it.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel


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


_CONTENT = b"the same bytes every time, so the hash matches"


async def _seed_existing(factory, *, stage: str) -> str:
    """A document already holding _CONTENT's hash, at the given stage."""
    import hashlib

    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(
            DocumentModel(
                id=doc_id,
                title="already here",
                format="txt",
                content_type="notes",
                word_count=5,
                page_count=1,
                file_path="/tmp/already-here.txt",
                file_hash=hashlib.sha256(_CONTENT).hexdigest(),
                stage=stage,
            )
        )
        await s.commit()
    return doc_id


async def _upload() -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post(
            "/documents/ingest",
            files={"file": ("already-here.txt", _CONTENT, "text/plain")},
        )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.anyio
async def test_reuploading_a_complete_document_reports_duplicate(test_db):
    """The regression this exists for: nothing runs, so nothing may claim to."""
    doc_id = await _seed_existing(test_db, stage="complete")

    body = await _upload()

    assert body["status"] == "duplicate"
    assert body["document_id"] == doc_id, "the caller is pointed at the copy we hold"


@pytest.mark.anyio
async def test_an_in_progress_duplicate_still_reports_processing(test_db):
    """A real job is behind it, and its progress is worth tracking."""
    await _seed_existing(test_db, stage="embedding")

    body = await _upload()

    assert body["status"] == "processing"


@pytest.mark.anyio
async def test_a_new_file_reports_processing(test_db, monkeypatch):
    """The ordinary path is untouched."""
    launched: list[str] = []
    from app.services import ingestion_jobs as jobs_module

    class _Jobs:
        def launch(self, doc_id, coro):
            launched.append(doc_id)
            coro.close()

    monkeypatch.setattr(jobs_module, "get_ingestion_jobs", lambda: _Jobs())
    import app.routers.documents as docs_router

    monkeypatch.setattr(docs_router, "get_ingestion_jobs", lambda: _Jobs())

    body = await _upload()

    assert body["status"] == "processing"
    assert launched, "a genuinely new file must actually start ingestion"
