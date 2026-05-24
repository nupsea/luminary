"""Polymorphic membership removal — 2A.5.

DELETE /collections/{id}/members/{member_id} accepts an optional member_type
query param. When given, deletes only the row of that type; when omitted,
deletes every row matching (collection_id, member_id) for back-compat.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import CollectionMemberModel, CollectionModel


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


async def _seed(factory, *, shared_id: str) -> str:
    """Seed a collection with both a note and a document sharing the same member_id."""
    col_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(CollectionModel(id=col_id, name="C"))
        s.add(
            CollectionMemberModel(
                id=str(uuid.uuid4()),
                collection_id=col_id,
                member_id=shared_id,
                member_type="note",
            )
        )
        s.add(
            CollectionMemberModel(
                id=str(uuid.uuid4()),
                collection_id=col_id,
                member_id=shared_id,
                member_type="document",
            )
        )
        await s.commit()
    return col_id


async def _types_left(factory, col_id: str, member_id: str) -> set[str]:
    async with factory() as s:
        rows = (
            await s.execute(
                select(CollectionMemberModel.member_type).where(
                    CollectionMemberModel.collection_id == col_id,
                    CollectionMemberModel.member_id == member_id,
                )
            )
        ).all()
    return {r[0] for r in rows}


@pytest.mark.anyio
async def test_remove_with_member_type_scopes_to_one_row(test_db):
    _, factory = test_db
    shared = str(uuid.uuid4())
    col_id = await _seed(factory, shared_id=shared)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(
            f"/collections/{col_id}/members/{shared}?member_type=document"
        )
        assert r.status_code == 204

    assert await _types_left(factory, col_id, shared) == {"note"}


@pytest.mark.anyio
async def test_remove_without_member_type_preserves_legacy_behaviour(test_db):
    _, factory = test_db
    shared = str(uuid.uuid4())
    col_id = await _seed(factory, shared_id=shared)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(f"/collections/{col_id}/members/{shared}")
        assert r.status_code == 204

    assert await _types_left(factory, col_id, shared) == set()


@pytest.mark.anyio
async def test_remove_wrong_type_is_noop(test_db):
    """If the member_type doesn't match any row, nothing is deleted (still 204)."""
    _, factory = test_db
    shared = str(uuid.uuid4())
    col_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(CollectionModel(id=col_id, name="C"))
        s.add(
            CollectionMemberModel(
                id=str(uuid.uuid4()),
                collection_id=col_id,
                member_id=shared,
                member_type="note",
            )
        )
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete(
            f"/collections/{col_id}/members/{shared}?member_type=document"
        )
        assert r.status_code == 204

    assert await _types_left(factory, col_id, shared) == {"note"}
