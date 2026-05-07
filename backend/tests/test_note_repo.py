"""Unit tests for NoteRepo (audit #9 fan-out)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import (
    CollectionMemberModel,
    NoteModel,
    NoteSourceModel,
)
from app.repos.note_repo import NoteRepo


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield NoteRepo(session)
    await engine.dispose()


def _make_note(
    *,
    id: str = "n1",
    content: str = "hello",
    document_id: str | None = "d1",
    section_id: str | None = None,
    content_hash: str | None = "h1",
    created_at: datetime | None = None,
) -> NoteModel:
    now = created_at or datetime.now(UTC)
    return NoteModel(
        id=id,
        content=content,
        document_id=document_id,
        section_id=section_id,
        content_hash=content_hash,
        tags=[],
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_stage_and_commit_persists(repo: NoteRepo) -> None:
    repo.stage(_make_note(id="n1"))
    await repo.commit()
    found = await repo.get_or_404("n1")
    assert found.id == "n1"


@pytest.mark.asyncio
async def test_get_or_404_missing(repo: NoteRepo) -> None:
    with pytest.raises(HTTPException) as ei:
        await repo.get_or_404("nope")
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_find_for_dedup_within_window(repo: NoteRepo) -> None:
    now = datetime.now(UTC)
    repo.stage(
        _make_note(id="n1", document_id="d1", section_id="s1", content_hash="abc", created_at=now)
    )
    await repo.commit()
    cutoff = now - timedelta(seconds=5)
    found = await repo.find_for_dedup(
        document_id="d1", section_id="s1", content_hash="abc", cutoff=cutoff
    )
    assert found is not None and found.id == "n1"

    stale_cutoff = now + timedelta(seconds=5)
    none = await repo.find_for_dedup(
        document_id="d1", section_id="s1", content_hash="abc", cutoff=stale_cutoff
    )
    assert none is None


@pytest.mark.asyncio
async def test_count_all(repo: NoteRepo) -> None:
    assert await repo.count_all() == 0
    repo.stage(_make_note(id="n1"))
    repo.stage(_make_note(id="n2"))
    await repo.commit()
    assert await repo.count_all() == 2


@pytest.mark.asyncio
async def test_autocomplete_content_prefix(repo: NoteRepo) -> None:
    repo.stage(_make_note(id="n1", content="apple pie"))
    repo.stage(_make_note(id="n2", content="banana split"))
    await repo.commit()
    rows = await repo.autocomplete_content("app")
    assert [r[0] for r in rows] == ["n1"]


@pytest.mark.asyncio
async def test_list_recent_orders_by_updated(repo: NoteRepo) -> None:
    older = datetime.now(UTC) - timedelta(hours=1)
    newer = datetime.now(UTC)
    repo.stage(_make_note(id="old", created_at=older))
    repo.stage(_make_note(id="new", created_at=newer))
    await repo.commit()
    rows = await repo.list_recent(limit=2)
    assert [r[0] for r in rows] == ["new", "old"]


@pytest.mark.asyncio
async def test_delete_by_id(repo: NoteRepo) -> None:
    repo.stage(_make_note(id="n1"))
    await repo.commit()
    await repo.delete_by_id("n1")
    with pytest.raises(HTTPException):
        await repo.get_or_404("n1")


@pytest.mark.asyncio
async def test_collection_and_source_lookups(repo: NoteRepo) -> None:
    repo.stage(_make_note(id="n1"))
    repo.session.add(
        CollectionMemberModel(
            id="m1", collection_id="c1", member_id="n1", member_type="note",
            added_at=datetime.now(UTC),
        )
    )
    repo.session.add(NoteSourceModel(note_id="n1", document_id="d2"))
    await repo.commit()
    assert await repo.collection_ids_for("n1") == ["c1"]
    assert await repo.source_document_ids_for("n1") == ["d2"]


@pytest.mark.asyncio
async def test_note_link_lifecycle(repo: NoteRepo) -> None:
    repo.stage(_make_note(id="src", content="src content"))
    repo.stage(_make_note(id="tgt", content="target content"))
    await repo.commit()

    assert await repo.find_link("src", "tgt", "see-also") is None

    link = await repo.create_link(
        source_note_id="src",
        target_note_id="tgt",
        link_type="see-also",
        created_at=datetime.now(UTC),
    )
    assert link.id

    same = await repo.find_link("src", "tgt", "see-also")
    assert same is not None and same.id == link.id

    out = await repo.outgoing_links_with_content("src")
    assert len(out) == 1 and out[0].content == "target content"

    inc = await repo.incoming_links_with_content("tgt")
    assert len(inc) == 1 and inc[0].content == "src content"

    await repo.delete_link(link)
    assert await repo.find_link("src", "tgt", "see-also") is None
