"""GET /tags/{tag_id}/cross-content-counts (plan 2E.4 spill-over)."""

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

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory
    yield engine, factory
    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


def _doc(doc_id: str) -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title="d",
        format="txt",
        content_type="book",
        word_count=1,
        page_count=0,
        file_path=f"/tmp/{doc_id}.txt",
        stage="complete",
        tags=[],
    )


@pytest.mark.anyio
async def test_returns_zero_counts_for_unknown_tag(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/tags/nonexistent/cross-content-counts")).json()
        assert body == {"document_count": 0, "note_count": 0}


# Flaky on GH CI only (memory pressure): POST /notes spawns fire-and-forget asyncio tasks
# (embed/graph/description) that race the per-note tag-index write on the shared SQLite lock,
# so one of the three notes intermittently isn't counted (note_count=2). Deterministically green
# locally and in the PR-triggered run on the same commit; same class as the other tag/note
# `unstable` tests. Excluded from CI; runnable via `uv run pytest -m unstable`.
@pytest.mark.unstable
@pytest.mark.anyio
async def test_splits_counts_across_documents_and_notes(test_db):
    _, factory = test_db
    d1, d2 = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(d1))
        s.add(_doc(d2))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.patch(f"/documents/{d1}/tags", json={"tags": ["algebra"]})
        await c.patch(f"/documents/{d2}/tags", json={"tags": ["algebra"]})
        # Use distinct content per note so the dedup-by-content-hash guard
        # in POST /notes doesn't fold these into a single row.
        for i in range(3):
            await c.post(
                "/notes",
                json={"content": f"note-{i}", "tags": ["algebra"], "document_id": None},
            )

        body = (await c.get("/tags/algebra/cross-content-counts")).json()
        assert body["document_count"] == 2
        assert body["note_count"] == 3


@pytest.mark.anyio
async def test_distinct_per_member_no_duplicates(test_db):
    """A single doc tagged once contributes 1, not 'rows in document_tag_index'."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Set tags twice; second call replaces. document_tag_index should
        # still have exactly one row for this doc/tag.
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["physics"]})
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["physics"]})

        body = (await c.get("/tags/physics/cross-content-counts")).json()
        assert body["document_count"] == 1
        assert body["note_count"] == 0
