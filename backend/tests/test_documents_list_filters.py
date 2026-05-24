"""SQL pushdown tests for GET /documents — 2A.4.

Cover: pagination correctness, total count with filters, combined filters,
empty-collection case, collection_id filter.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import (
    CollectionMemberModel,
    CollectionModel,
    DocumentModel,
)


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


def _make_doc(
    *,
    title: str,
    content_type: str = "book",
    tags: list[str] | None = None,
    created_at: datetime | None = None,
) -> DocumentModel:
    return DocumentModel(
        id=str(uuid.uuid4()),
        title=title,
        format="txt",
        content_type=content_type,
        word_count=10,
        page_count=1,
        file_path="/tmp/x.txt",
        stage="complete",
        tags=tags or [],
        created_at=created_at or datetime.now(UTC),
    )


def _make_collection(name: str = "C") -> CollectionModel:
    return CollectionModel(id=str(uuid.uuid4()), name=name)


@pytest.mark.anyio
async def test_pagination_total_and_page_window(test_db):
    _, factory = test_db
    base = datetime.now(UTC)
    async with factory() as s:
        for i in range(25):
            s.add(_make_doc(title=f"Doc {i:02d}", created_at=base - timedelta(seconds=i)))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        p1 = (await c.get("/documents?page=1&page_size=10")).json()
        p2 = (await c.get("/documents?page=2&page_size=10")).json()
        p3 = (await c.get("/documents?page=3&page_size=10")).json()
        assert p1["total"] == 25
        assert p2["total"] == 25
        assert len(p1["items"]) == 10
        assert len(p2["items"]) == 10
        assert len(p3["items"]) == 5
        ids = {d["id"] for d in p1["items"] + p2["items"] + p3["items"]}
        assert len(ids) == 25


@pytest.mark.anyio
async def test_content_type_filter_total_reflects_filter(test_db):
    _, factory = test_db
    async with factory() as s:
        for i in range(5):
            s.add(_make_doc(title=f"B{i}", content_type="book"))
        for i in range(3):
            s.add(_make_doc(title=f"P{i}", content_type="paper"))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = (await c.get("/documents?content_type=book")).json()
        assert r["total"] == 5
        assert all(d["content_type"] == "book" for d in r["items"])

        r = (await c.get("/documents?content_type=book,paper")).json()
        assert r["total"] == 8


@pytest.mark.anyio
async def test_combined_content_type_and_tag_filter(test_db):
    _, factory = test_db
    a = _make_doc(title="A", content_type="book")
    b = _make_doc(title="B", content_type="book")
    cdoc = _make_doc(title="C", content_type="paper")
    async with factory() as s:
        s.add(a)
        s.add(b)
        s.add(cdoc)
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.patch(f"/documents/{a.id}/tags", json={"tags": ["physics"]})
        await c.patch(f"/documents/{b.id}/tags", json={"tags": ["history"]})
        await c.patch(f"/documents/{cdoc.id}/tags", json={"tags": ["physics"]})

        r = (await c.get("/documents?content_type=book&tag=physics")).json()
        assert r["total"] == 1
        assert r["items"][0]["title"] == "A"


@pytest.mark.anyio
async def test_collection_id_filter_returns_members_only(test_db):
    _, factory = test_db
    async with factory() as s:
        col = _make_collection("Reading")
        s.add(col)
        d_in = _make_doc(title="In", content_type="book")
        d_out = _make_doc(title="Out", content_type="book")
        s.add(d_in)
        s.add(d_out)
        s.add(
            CollectionMemberModel(
                id=str(uuid.uuid4()),
                collection_id=col.id,
                member_id=d_in.id,
                member_type="document",
            )
        )
        await s.commit()
        cid = col.id
        in_id = d_in.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = (await c.get(f"/documents?collection_id={cid}")).json()
        assert r["total"] == 1
        assert r["items"][0]["id"] == in_id


@pytest.mark.anyio
async def test_collection_id_filter_ignores_note_memberships(test_db):
    """A note-typed membership row with the same member_id must not leak documents in."""
    _, factory = test_db
    async with factory() as s:
        col = _make_collection("Mixed")
        s.add(col)
        d = _make_doc(title="D", content_type="book")
        s.add(d)
        # Note membership using doc.id as member_id -- should NOT match.
        s.add(
            CollectionMemberModel(
                id=str(uuid.uuid4()),
                collection_id=col.id,
                member_id=d.id,
                member_type="note",
            )
        )
        await s.commit()
        cid = col.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = (await c.get(f"/documents?collection_id={cid}")).json()
        assert r["total"] == 0
        assert r["items"] == []


@pytest.mark.anyio
async def test_empty_collection_returns_zero(test_db):
    _, factory = test_db
    async with factory() as s:
        col = _make_collection("Empty")
        s.add(col)
        s.add(_make_doc(title="Loose", content_type="book"))
        await s.commit()
        cid = col.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = (await c.get(f"/documents?collection_id={cid}")).json()
        assert r["total"] == 0
        assert r["items"] == []


@pytest.mark.anyio
async def test_alphabetical_sort_with_pagination(test_db):
    _, factory = test_db
    async with factory() as s:
        for name in ["Charlie", "alpha", "Bravo", "delta", "Echo"]:
            s.add(_make_doc(title=name))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = (await c.get("/documents?sort=alphabetical&page=1&page_size=3")).json()
        titles = [i["title"] for i in r["items"]]
        assert titles == ["alpha", "Bravo", "Charlie"]
        r2 = (await c.get("/documents?sort=alphabetical&page=2&page_size=3")).json()
        assert [i["title"] for i in r2["items"]] == ["delta", "Echo"]
