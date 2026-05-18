"""Unit tests for ClipRepo (audit #9 proof-of-pattern)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.repos.clip_repo import ClipRepo


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield ClipRepo(session)
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_assigns_id_and_timestamps(repo: ClipRepo) -> None:
    clip = await repo.create(
        document_id="doc-1",
        section_id=None,
        section_heading=None,
        pdf_page_number=None,
        selected_text="hello",
        user_note="",
    )
    assert clip.id
    assert clip.document_id == "doc-1"
    assert clip.created_at == clip.updated_at


@pytest.mark.asyncio
async def test_list_orders_newest_first(repo: ClipRepo) -> None:
    a = await repo.create(
        document_id="d", section_id=None, section_heading=None,
        pdf_page_number=None, selected_text="A", user_note="",
    )
    b = await repo.create(
        document_id="d", section_id=None, section_heading=None,
        pdf_page_number=None, selected_text="B", user_note="",
    )
    rows = await repo.list()
    ids = [r.id for r in rows]
    assert ids.index(b.id) < ids.index(a.id)


@pytest.mark.asyncio
async def test_list_filters_by_document(repo: ClipRepo) -> None:
    await repo.create(
        document_id="x", section_id=None, section_heading=None,
        pdf_page_number=None, selected_text="X-only", user_note="",
    )
    await repo.create(
        document_id="y", section_id=None, section_heading=None,
        pdf_page_number=None, selected_text="Y-only", user_note="",
    )
    rows = await repo.list(document_id="x")
    assert len(rows) == 1 and rows[0].selected_text == "X-only"


@pytest.mark.asyncio
async def test_get_or_404_missing_raises(repo: ClipRepo) -> None:
    with pytest.raises(HTTPException) as excinfo:
        await repo.get_or_404("nope")
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_update_note_persists_and_bumps_updated_at(repo: ClipRepo) -> None:
    clip = await repo.create(
        document_id="d", section_id=None, section_heading=None,
        pdf_page_number=None, selected_text="t", user_note="",
    )
    original_updated_at = clip.updated_at
    updated = await repo.update_note(clip.id, user_note="annotated")
    assert updated.user_note == "annotated"
    assert updated.updated_at >= original_updated_at


@pytest.mark.asyncio
async def test_delete_then_get_404(repo: ClipRepo) -> None:
    clip = await repo.create(
        document_id="d", section_id=None, section_heading=None,
        pdf_page_number=None, selected_text="t", user_note="",
    )
    await repo.delete(clip.id)
    with pytest.raises(HTTPException) as excinfo:
        await repo.get_or_404(clip.id)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_missing_raises_404(repo: ClipRepo) -> None:
    with pytest.raises(HTTPException) as excinfo:
        await repo.delete("nope")
    assert excinfo.value.status_code == 404
