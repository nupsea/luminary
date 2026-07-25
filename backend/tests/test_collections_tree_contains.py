"""?contains scope on /collections/tree (redesign-phase-2-plan 2E.1c)."""

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
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory
    yield engine, factory

    # Clean up note creation background tasks to avoid engine.dispose hang
    import asyncio

    from app.routers.notes import _background_tasks
    pending = list(_background_tasks)
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    _background_tasks.clear()

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


async def _create_collection(c: AsyncClient, name: str, parent: str | None = None) -> str:
    body: dict = {"name": name}
    if parent:
        body["parent_collection_id"] = parent
    r = await c.post("/collections", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.anyio
async def test_tree_unscoped_scoped_count_sums_direct_members(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        col_id = await _create_collection(c, "Top")
        await c.post(
            f"/collections/{col_id}/members",
            json={"member_ids": [doc_id], "member_type": "document"},
        )
        note_resp = await c.post("/notes", json={"content": "n", "tags": [], "document_id": None})
        note_id = note_resp.json()["id"]
        await c.post(
            f"/collections/{col_id}/members",
            json={"member_ids": [note_id], "member_type": "note"},
        )

        tree = (await c.get("/collections/tree")).json()
        node = next(n for n in tree if n["id"] == col_id)
        assert node["document_count"] == 1
        assert node["note_count"] == 1
        assert node["scoped_count"] == 2  # unscoped = direct doc + note


@pytest.mark.anyio
async def test_tree_contains_scopes_counts_without_hiding_collections(test_db):
    """?contains scopes scoped_count; it never removes a collection from the list.

    A note-only collection must stay reachable from the Library rail, or a
    document can never be dropped into it.
    """
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        notes_only = await _create_collection(c, "NotesOnly")
        note_resp = await c.post("/notes", json={"content": "n", "tags": [], "document_id": None})
        await c.post(
            f"/collections/{notes_only}/members",
            json={"member_ids": [note_resp.json()["id"]], "member_type": "note"},
        )

        docs_only = await _create_collection(c, "DocsOnly")
        await c.post(
            f"/collections/{docs_only}/members",
            json={"member_ids": [doc_id], "member_type": "document"},
        )

        tree = (await c.get("/collections/tree?contains=document")).json()
        ids = {n["id"] for n in tree}
        assert docs_only in ids
        assert notes_only in ids, "a note-only collection must stay droppable from the Library"

        docs_node = next(n for n in tree if n["id"] == docs_only)
        assert docs_node["scoped_count"] == 1
        notes_node = next(n for n in tree if n["id"] == notes_only)
        assert notes_node["scoped_count"] == 0
        assert notes_node["note_count"] == 1


@pytest.mark.anyio
async def test_tree_contains_preserves_ancestor_when_only_child_matches(test_db):
    """parent has no direct docs, child has 1 doc: ?contains=document keeps both."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        parent_id = await _create_collection(c, "Parent")
        child_id = await _create_collection(c, "Child", parent=parent_id)
        await c.post(
            f"/collections/{child_id}/members",
            json={"member_ids": [doc_id], "member_type": "document"},
        )

        tree = (await c.get("/collections/tree?contains=document")).json()
        parent_node = next((n for n in tree if n["id"] == parent_id), None)
        assert parent_node is not None, "parent must survive because a descendant matches"
        # Parent has no direct docs; inclusive scoped_count comes from child.
        assert parent_node["scoped_count"] == 1
        child_ids = {c["id"] for c in parent_node["children"]}
        assert child_id in child_ids


@pytest.mark.anyio
async def test_tree_contains_keeps_empty_collections(test_db):
    """Empty collections must survive any scope filter so create-then-add works."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        empty_id = await _create_collection(c, "Brand new")

        tree = (await c.get("/collections/tree?contains=document")).json()
        ids = {n["id"] for n in tree}
        assert empty_id in ids
        node = next(n for n in tree if n["id"] == empty_id)
        assert node["scoped_count"] == 0


@pytest.mark.anyio
async def test_counts_ignore_members_whose_target_was_deleted(test_db):
    """A deleted note must leave no trace in its collection's badge.

    Membership keys on (member_id, member_type), so nothing cascades to it
    automatically. When that was missed, a 2-note collection reported five.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        col_id = await _create_collection(c, "Survivors")

        note_ids = []
        for i in range(3):
            r = await c.post("/notes", json={"content": f"n{i}", "tags": [], "document_id": None})
            note_ids.append(r.json()["id"])
        await c.post(
            f"/collections/{col_id}/members",
            json={"member_ids": note_ids, "member_type": "note"},
        )

        node = next(n for n in (await c.get("/collections/tree")).json() if n["id"] == col_id)
        assert node["note_count"] == 3

        assert (await c.delete(f"/notes/{note_ids[0]}")).status_code in (200, 204)

        node = next(n for n in (await c.get("/collections/tree")).json() if n["id"] == col_id)
        assert node["note_count"] == 2, "deleted note still counted in the collection badge"


@pytest.mark.anyio
async def test_deleting_a_document_clears_its_memberships(test_db):
    """The document delete cascade must reach collection_members too."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        col_id = await _create_collection(c, "Docs")
        await c.post(
            f"/collections/{col_id}/members",
            json={"member_ids": [doc_id], "member_type": "document"},
        )
        node = next(n for n in (await c.get("/collections/tree")).json() if n["id"] == col_id)
        assert node["document_count"] == 1

        assert (await c.delete(f"/documents/{doc_id}")).status_code in (200, 204)

        node = next(n for n in (await c.get("/collections/tree")).json() if n["id"] == col_id)
        assert node["document_count"] == 0


@pytest.mark.anyio
async def test_tree_contains_invalid_returns_422(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/collections/tree?contains=spaceship")
        assert r.status_code == 422
