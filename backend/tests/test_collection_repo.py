"""Unit tests for CollectionRepo."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.repos.collection_repo import CollectionRepo


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield CollectionRepo(session)
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_get(repo: CollectionRepo) -> None:
    col = await repo.create(name="Notes")
    fetched = await repo.get_or_404(col.id)
    assert fetched.name == "Notes"


@pytest.mark.asyncio
async def test_get_or_404_missing_raises(repo: CollectionRepo) -> None:
    with pytest.raises(HTTPException) as excinfo:
        await repo.get_or_404("nope")
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_list_all_orders_by_sort_then_name(repo: CollectionRepo) -> None:
    await repo.create(name="B", sort_order=1)
    await repo.create(name="A", sort_order=2)
    await repo.create(name="C", sort_order=1)
    rows = await repo.list_all()
    assert [r.name for r in rows] == ["B", "C", "A"]


@pytest.mark.asyncio
async def test_find_by_auto_document_id(repo: CollectionRepo) -> None:
    await repo.create(name="Auto-DDIA", auto_document_id="doc-1")
    found = await repo.find_by_auto_document_id("doc-1")
    assert found is not None and found.name == "Auto-DDIA"
    assert await repo.find_by_auto_document_id("nope") is None


@pytest.mark.asyncio
async def test_update_fields_only_updates_supplied(repo: CollectionRepo) -> None:
    col = await repo.create(name="Original", color="#000000")
    updated = await repo.update_fields(col, name="Renamed")
    assert updated.name == "Renamed"
    assert updated.color == "#000000"


@pytest.mark.asyncio
async def test_add_members_idempotent(repo: CollectionRepo) -> None:
    col = await repo.create(name="C")
    await repo.add_members(col.id, ["m1", "m2"], member_type="note")
    await repo.add_members(col.id, ["m1", "m3"], member_type="note")  # m1 dedup'd
    assert await repo.count_members(col.id) == 3


@pytest.mark.asyncio
async def test_remove_member(repo: CollectionRepo) -> None:
    col = await repo.create(name="C")
    await repo.add_members(col.id, ["m1", "m2"], member_type="note")
    await repo.remove_member(col.id, "m1")
    assert await repo.count_members(col.id) == 1


@pytest.mark.asyncio
async def test_member_counts_groups_by_type(repo: CollectionRepo) -> None:
    col = await repo.create(name="C")
    await repo.add_members(col.id, ["n1", "n2"], member_type="note")
    await repo.add_members(col.id, ["d1"], member_type="document")
    counts = await repo.member_counts()
    assert counts[(col.id, "note")] == 2
    assert counts[(col.id, "document")] == 1


@pytest.mark.asyncio
async def test_delete_with_children_cascades(repo: CollectionRepo) -> None:
    parent = await repo.create(name="Parent")
    child = await repo.create(name="Child", parent_collection_id=parent.id)
    await repo.add_members(parent.id, ["m1"], member_type="note")
    await repo.add_members(child.id, ["m2"], member_type="note")

    await repo.delete_with_children(parent.id)

    with pytest.raises(HTTPException):
        await repo.get_or_404(parent.id)
    with pytest.raises(HTTPException):
        await repo.get_or_404(child.id)
    assert await repo.count_members(parent.id) == 0
    assert await repo.count_members(child.id) == 0


@pytest.mark.asyncio
async def test_child_ids(repo: CollectionRepo) -> None:
    parent = await repo.create(name="P")
    c1 = await repo.create(name="C1", parent_collection_id=parent.id)
    c2 = await repo.create(name="C2", parent_collection_id=parent.id)
    await repo.create(name="Other")
    ids = set(await repo.child_ids(parent.id))
    assert ids == {c1.id, c2.id}
