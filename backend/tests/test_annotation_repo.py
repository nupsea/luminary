"""Unit tests for AnnotationRepo."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.repos.annotation_repo import AnnotationRepo


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield AnnotationRepo(session)
    await engine.dispose()


def _kwargs(**overrides):
    base = dict(
        document_id="doc-1",
        section_id="sec-1",
        chunk_id=None,
        selected_text="hello",
        start_offset=0,
        end_offset=5,
        color="yellow",
        note_text=None,
        page_number=None,
    )
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_create_assigns_id_and_created_at(repo: AnnotationRepo) -> None:
    a = await repo.create(**_kwargs())
    assert a.id and a.created_at is not None


@pytest.mark.asyncio
async def test_list_for_document_filters_and_orders(repo: AnnotationRepo) -> None:
    a = await repo.create(**_kwargs(document_id="d-a", selected_text="A"))
    b = await repo.create(**_kwargs(document_id="d-a", selected_text="B"))
    await repo.create(**_kwargs(document_id="d-b", selected_text="C"))
    rows = await repo.list_for_document("d-a")
    ids = [r.id for r in rows]
    assert ids == [a.id, b.id]


@pytest.mark.asyncio
async def test_delete_then_list_empty(repo: AnnotationRepo) -> None:
    a = await repo.create(**_kwargs(document_id="d-x"))
    await repo.delete(a.id)
    assert await repo.list_for_document("d-x") == []


@pytest.mark.asyncio
async def test_delete_missing_raises_404(repo: AnnotationRepo) -> None:
    with pytest.raises(HTTPException) as excinfo:
        await repo.delete("nope")
    assert excinfo.value.status_code == 404
