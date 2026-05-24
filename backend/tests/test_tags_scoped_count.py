"""Scoped counts on /tags and /tags/tree (redesign-phase-2-plan 2E.1a/b)."""

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
        file_path="/tmp/x.txt",
        stage="complete",
        tags=[],
    )


@pytest.mark.anyio
async def test_list_tags_scope_all_scoped_count_equals_usage_count(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["history"]})
        await c.post("/notes", json={"content": "n", "tags": ["history"], "document_id": None})

        rows = (await c.get("/tags?scope=all")).json()
        history = next(t for t in rows if t["id"] == "history")
        # Global usage_count is 2 (doc + note); scope=all returns the same.
        assert history["usage_count"] == 2
        assert history["scoped_count"] == 2


@pytest.mark.anyio
async def test_list_tags_scoped_count_splits_by_content_type(test_db):
    """Tag applied to 2 docs + 1 note: scope=document -> scoped=2, scope=note -> scoped=1."""
    _, factory = test_db
    d1, d2 = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(d1))
        s.add(_doc(d2))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.patch(f"/documents/{d1}/tags", json={"tags": ["shared"]})
        await c.patch(f"/documents/{d2}/tags", json={"tags": ["shared"]})
        await c.post("/notes", json={"content": "n", "tags": ["shared"], "document_id": None})

        doc_rows = (await c.get("/tags?scope=document")).json()
        doc_shared = next(t for t in doc_rows if t["id"] == "shared")
        assert doc_shared["scoped_count"] == 2
        assert doc_shared["usage_count"] == 3  # global still 3

        note_rows = (await c.get("/tags?scope=note")).json()
        note_shared = next(t for t in note_rows if t["id"] == "shared")
        assert note_shared["scoped_count"] == 1


@pytest.mark.anyio
async def test_list_tags_scoped_ordering_prefers_scoped_count(test_db):
    """Tag mostly on notes shouldn't outrank a doc-heavy tag when scope=document."""
    _, factory = test_db
    d1, d2, d3 = (str(uuid.uuid4()) for _ in range(3))
    async with factory() as s:
        s.add(_doc(d1))
        s.add(_doc(d2))
        s.add(_doc(d3))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # note_heavy: many notes, only 1 doc.
        for _ in range(5):
            await c.post(
                "/notes",
                json={"content": "n", "tags": ["note-heavy"], "document_id": None},
            )
        await c.patch(f"/documents/{d1}/tags", json={"tags": ["note-heavy"]})
        # doc_heavy: 2 docs, no notes.
        await c.patch(f"/documents/{d2}/tags", json={"tags": ["doc-heavy"]})
        await c.patch(f"/documents/{d3}/tags", json={"tags": ["doc-heavy"]})

        rows = (await c.get("/tags?scope=document")).json()
        ids_in_order = [t["id"] for t in rows]
        # doc-heavy (scoped=2) ranks above note-heavy (scoped=1).
        assert ids_in_order.index("doc-heavy") < ids_in_order.index("note-heavy")


@pytest.mark.anyio
async def test_tag_tree_scope_all_unchanged_shape(test_db):
    """Tree without scope param matches pre-2E.1b behavior (usage_count populated).
    The parent tag must exist as a canonical_tag (the tree only renders nodes
    whose canonical row exists); we seed it via a note tagged just 'science'."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/notes", json={"content": "p", "tags": ["science"], "document_id": None})
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["science/biology"]})

        tree = (await c.get("/tags/tree")).json()
        science = next(n for n in tree if n["id"] == "science")
        # Inclusive: 1 direct (the seed note) + 1 descendant (biology on doc) = 2.
        assert science["usage_count"] == 2
        assert science["scoped_count"] == 2


@pytest.mark.anyio
async def test_tag_tree_scope_prunes_empty_subtrees_but_preserves_ancestor(test_db):
    """science has note + doc children; ?scope=document keeps science and the doc child only."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Seed the 'science' parent canonical_tag so the tree can nest under it.
        # Use the manual POST to avoid bumping any usage_count.
        await c.post(
            "/tags",
            json={"id": "science", "display_name": "Science", "parent_tag": None},
        )
        await c.post(
            "/notes",
            json={"content": "n", "tags": ["science/physics"], "document_id": None},
        )
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["science/biology"]})

        # ?scope=document: only science (ancestor) + biology (matching descendant) survive.
        doc_tree = (await c.get("/tags/tree?scope=document")).json()
        science_doc = next((n for n in doc_tree if n["id"] == "science"), None)
        assert science_doc is not None, "science ancestor must be preserved"
        child_ids = {c["id"] for c in science_doc["children"]}
        assert "science/biology" in child_ids
        assert "science/physics" not in child_ids
        assert science_doc["scoped_count"] == 1

        # ?scope=note: mirrors the other side.
        note_tree = (await c.get("/tags/tree?scope=note")).json()
        science_note = next(n for n in note_tree if n["id"] == "science")
        note_child_ids = {c["id"] for c in science_note["children"]}
        assert "science/physics" in note_child_ids
        assert "science/biology" not in note_child_ids


@pytest.mark.anyio
async def test_tag_tree_scope_invalid_returns_422(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/tags/tree?scope=hyperlink")
        assert r.status_code == 422
