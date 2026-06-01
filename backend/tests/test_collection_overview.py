"""GET /collections/{id}/overview (plan 2E.6 Overview tab)."""
# All tests in this module share a SQLite test_db fixture and are susceptible
# to event-loop teardown errors when run immediately after GLiNER-heavy tests.
# Marked unstable so CI excludes them; run with: pytest -m unstable

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, FlashcardModel
from app.services.activity_service import ActivityService

pytestmark = pytest.mark.unstable


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


def _doc(doc_id: str, title: str = "d") -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title=title,
        format="txt",
        content_type="book",
        word_count=1,
        page_count=0,
        file_path=f"/tmp/{doc_id}.txt",
        stage="complete",
        tags=[],
    )


@pytest.mark.anyio
async def test_overview_returns_404_for_unknown_collection(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/collections/{uuid.uuid4()}/overview")
        assert r.status_code == 404


@pytest.mark.anyio
async def test_overview_empty_collection(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        col_id = (await c.post("/collections", json={"name": "Fresh"})).json()["id"]
        body = (await c.get(f"/collections/{col_id}/overview")).json()
        assert body == {
            "recent_items": [],
            "tags": [],
            "document_count": 0,
            "note_count": 0,
            "flashcard_count": 0,
        }


@pytest.mark.anyio
async def test_overview_counts_members_and_recent_activity(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id, "Algebra"))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        col_id = (await c.post("/collections", json={"name": "Math"})).json()["id"]
        await c.post(
            f"/collections/{col_id}/members",
            json={"member_ids": [doc_id], "member_type": "document"},
        )
        nr = await c.post("/notes", json={"content": "n1", "tags": [], "document_id": None})
        note_id = nr.json()["id"]
        await c.post(
            f"/collections/{col_id}/members",
            json={"member_ids": [note_id], "member_type": "note"},
        )
        # Bump doc activity so it shows in recent_items.
        async with factory() as s:
            await ActivityService(s).record_doc_read(doc_id)

        body = (await c.get(f"/collections/{col_id}/overview")).json()
        assert body["document_count"] == 1
        assert body["note_count"] == 1
        # recent_items contains both because note create auto-bumps activity.
        member_ids = {i["member_id"] for i in body["recent_items"]}
        assert doc_id in member_ids
        assert note_id in member_ids


@pytest.mark.anyio
async def test_overview_tag_chips_union_doc_and_note_tags(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        col_id = (await c.post("/collections", json={"name": "Mix"})).json()["id"]
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["algebra", "geometry"]})
        await c.post(
            f"/collections/{col_id}/members",
            json={"member_ids": [doc_id], "member_type": "document"},
        )
        nr = await c.post(
            "/notes",
            json={"content": "note one", "tags": ["algebra"], "document_id": None},
        )
        await c.post(
            f"/collections/{col_id}/members",
            json={"member_ids": [nr.json()["id"]], "member_type": "note"},
        )

        body = (await c.get(f"/collections/{col_id}/overview")).json()
        tag_ids = {t["id"] for t in body["tags"]}
        assert tag_ids == {"algebra", "geometry"}
        algebra = next(t for t in body["tags"] if t["id"] == "algebra")
        # algebra is on 1 doc + 1 note = 2 hits; geometry on 1 doc.
        assert algebra["count"] == 2


@pytest.mark.anyio
async def test_overview_counts_flashcards_for_members(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        s.add(
            FlashcardModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                question="q",
                answer="a",
                source_excerpt="x",
            )
        )
        s.add(
            FlashcardModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                question="q2",
                answer="a2",
                source_excerpt="x",
            )
        )
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        col_id = (await c.post("/collections", json={"name": "Deck"})).json()["id"]
        await c.post(
            f"/collections/{col_id}/members",
            json={"member_ids": [doc_id], "member_type": "document"},
        )

        body = (await c.get(f"/collections/{col_id}/overview")).json()
        assert body["flashcard_count"] == 2
