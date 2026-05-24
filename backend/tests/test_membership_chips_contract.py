"""Membership chip data on /documents and /notes list endpoints (plan 2E.5).

Verifies the additive `collections` field on DocumentListItem and the
collection_ids -> collections migration on NoteResponse. Card UI consuming
these chips lands in step 8; the contract must lock first.
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


async def _create_collection(
    c: AsyncClient, name: str, color: str = "#6366F1", sort_order: int = 0
) -> tuple[str, str, str]:
    """Returns (id, normalized_name, color). Name is normalized by the router."""
    body = {"name": name, "color": color, "sort_order": sort_order}
    r = await c.post("/collections", json=body)
    assert r.status_code == 201, r.text
    j = r.json()
    return j["id"], j["name"], j["color"]


@pytest.mark.anyio
async def test_documents_list_empty_collections_for_unaffiliated_doc(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        items = (await c.get("/documents")).json()["items"]
        item = next(i for i in items if i["id"] == doc_id)
        assert item["collections"] == []


@pytest.mark.anyio
async def test_documents_list_emits_collection_refs_for_member(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        col_id, col_name, color = await _create_collection(c, "Algebra", color="#FF00AA")
        await c.post(
            f"/collections/{col_id}/members",
            json={"member_ids": [doc_id], "member_type": "document"},
        )

        items = (await c.get("/documents")).json()["items"]
        item = next(i for i in items if i["id"] == doc_id)
        assert item["collections"] == [{"id": col_id, "name": col_name, "color": color}]


@pytest.mark.anyio
async def test_documents_list_collections_ordered_by_sort_order(test_db):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        cid_b, name_b, _ = await _create_collection(c, "Beta", sort_order=20)
        cid_a, name_a, _ = await _create_collection(c, "Alpha", sort_order=10)
        cid_g, name_g, _ = await _create_collection(c, "Gamma", sort_order=30)
        for cid in [cid_g, cid_b, cid_a]:
            await c.post(
                f"/collections/{cid}/members",
                json={"member_ids": [doc_id], "member_type": "document"},
            )

        items = (await c.get("/documents")).json()["items"]
        item = next(i for i in items if i["id"] == doc_id)
        ids_in_order = [c["id"] for c in item["collections"]]
        assert ids_in_order == [cid_a, cid_b, cid_g]
        names_in_order = [c["name"] for c in item["collections"]]
        assert names_in_order == [name_a, name_b, name_g]


@pytest.mark.anyio
async def test_notes_list_collections_replaces_collection_ids(test_db):
    """NoteResponse.collection_ids was list[str]; now collections is list[CollectionRef]."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        col_id, col_name, color = await _create_collection(c, "Inbox", color="#33CC88")
        note_resp = await c.post(
            "/notes",
            json={"content": "x", "tags": [], "document_id": None},
        )
        note_id = note_resp.json()["id"]
        await c.post(
            f"/collections/{col_id}/members",
            json={"member_ids": [note_id], "member_type": "note"},
        )

        notes = (await c.get("/notes")).json()
        item = next(n for n in notes if n["id"] == note_id)
        assert "collection_ids" not in item
        assert item["collections"] == [{"id": col_id, "name": col_name, "color": color}]


@pytest.mark.unstable
@pytest.mark.anyio
async def test_get_note_returns_collections_with_refs(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        col_id, col_name, color = await _create_collection(c, "Reading list", color="#0044FF")
        note_resp = await c.post(
            "/notes",
            json={"content": "x", "tags": [], "document_id": None},
        )
        note_id = note_resp.json()["id"]
        await c.post(
            f"/collections/{col_id}/members",
            json={"member_ids": [note_id], "member_type": "note"},
        )

        single = (await c.get(f"/notes/{note_id}")).json()
        assert "collection_ids" not in single
        assert single["collections"] == [{"id": col_id, "name": col_name, "color": color}]
