"""Unit tests for TagRepo (audit #9 fan-out)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import NoteModel, NoteTagIndexModel, TagAliasModel
from app.repos.tag_repo import TagRepo


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield TagRepo(session)
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_find(repo: TagRepo) -> None:
    tag = await repo.create(id="science", display_name="Science", parent_tag=None)
    assert tag.id == "science"
    found = await repo.find_by_id("science")
    assert found is not None and found.display_name == "Science"


@pytest.mark.asyncio
async def test_find_missing_returns_none(repo: TagRepo) -> None:
    assert await repo.find_by_id("nope") is None


@pytest.mark.asyncio
async def test_get_or_404_raises(repo: TagRepo) -> None:
    with pytest.raises(HTTPException) as excinfo:
        await repo.get_or_404("nope")
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_list_by_count_orders_desc(repo: TagRepo) -> None:
    await repo.create(id="a", display_name="A", parent_tag=None)
    await repo.create(id="b", display_name="B", parent_tag=None)
    # Bump b's note_count
    b = await repo.get_or_404("b")
    b.note_count = 5
    await repo.session.commit()
    rows = await repo.list_by_count()
    assert [r.id for r in rows[:2]] == ["b", "a"]


@pytest.mark.asyncio
async def test_autocomplete_prefix(repo: TagRepo) -> None:
    await repo.create(id="science", display_name="Science", parent_tag=None)
    await repo.create(id="science/biology", display_name="Biology", parent_tag="science")
    await repo.create(id="math", display_name="Math", parent_tag=None)
    rows = await repo.autocomplete("scien")
    ids = {r.id for r in rows}
    assert ids == {"science", "science/biology"}


@pytest.mark.asyncio
async def test_note_ids_with_tag_descendants(repo: TagRepo) -> None:
    repo.session.add(
        NoteTagIndexModel(note_id="n1", tag_full="science", tag_root="science", tag_parent="")
    )
    repo.session.add(
        NoteTagIndexModel(
            note_id="n2",
            tag_full="science/biology",
            tag_root="science",
            tag_parent="science",
        )
    )
    repo.session.add(
        NoteTagIndexModel(note_id="n3", tag_full="math", tag_root="math", tag_parent="")
    )
    await repo.session.commit()

    direct = await repo.note_ids_with_tag("science")
    assert set(direct) == {"n1"}

    inclusive = await repo.note_ids_with_tag("science", include_descendants=True)
    assert set(inclusive) == {"n1", "n2"}


@pytest.mark.asyncio
async def test_load_notes_filters_by_id(repo: TagRepo) -> None:
    from datetime import UTC, datetime  # noqa: PLC0415

    now = datetime.now(UTC)
    repo.session.add(
        NoteModel(id="n1", content="hello", tags=["x"], created_at=now, updated_at=now)
    )
    repo.session.add(
        NoteModel(id="n2", content="world", tags=["y"], created_at=now, updated_at=now)
    )
    await repo.session.commit()
    rows = await repo.load_notes(["n1"])
    assert [r.id for r in rows] == ["n1"]
    assert await repo.load_notes([]) == []


@pytest.mark.asyncio
async def test_update_fields_partial(repo: TagRepo) -> None:
    tag = await repo.create(id="x", display_name="X", parent_tag=None)
    updated = await repo.update_fields(tag, display_name="X-renamed")
    assert updated.display_name == "X-renamed"
    assert updated.parent_tag is None

    # parent_tag_set=True with None clears
    tag2 = await repo.create(id="y", display_name="Y", parent_tag="root")
    cleared = await repo.update_fields(tag2, parent_tag=None, parent_tag_set=True)
    assert cleared.parent_tag is None


@pytest.mark.asyncio
async def test_delete_with_aliases(repo: TagRepo) -> None:
    await repo.create(id="src", display_name="Src", parent_tag=None)
    await repo.create(id="dst", display_name="Dst", parent_tag=None)
    repo.session.add(TagAliasModel(alias="old", canonical_tag_id="src"))
    await repo.session.commit()

    await repo.delete_with_aliases("src")

    assert await repo.find_by_id("src") is None
    # alias removed too
    from sqlalchemy import select  # noqa: PLC0415

    rows = (
        await repo.session.execute(
            select(TagAliasModel).where(TagAliasModel.canonical_tag_id == "src")
        )
    ).scalars().all()
    assert rows == []
