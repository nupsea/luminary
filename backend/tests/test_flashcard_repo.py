"""Unit tests for FlashcardRepo (audit #9 fan-out)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, FlashcardModel
from app.repos.flashcard_repo import FlashcardRepo


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield FlashcardRepo(session)
    await engine.dispose()


def _make_card(
    *,
    id: str,
    document_id: str = "doc-1",
    chunk_id: str | None = None,
    bloom_level: int | None = None,
    created_at: datetime | None = None,
) -> FlashcardModel:
    now = created_at or datetime.now(UTC)
    return FlashcardModel(
        id=id,
        document_id=document_id,
        chunk_id=chunk_id,
        source="document",
        deck="default",
        question=f"q-{id}",
        answer=f"a-{id}",
        source_excerpt="excerpt",
        difficulty="medium",
        bloom_level=bloom_level,
        created_at=now,
        due_date=now,
    )


@pytest.mark.asyncio
async def test_get_or_404_missing(repo: FlashcardRepo) -> None:
    with pytest.raises(HTTPException) as ei:
        await repo.get_or_404("nope")
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_list_for_document_orders_desc(repo: FlashcardRepo) -> None:
    older = datetime.now(UTC).replace(microsecond=0)
    newer = datetime.now(UTC).replace(microsecond=500000)
    repo.session.add(_make_card(id="a", created_at=older))
    repo.session.add(_make_card(id="b", created_at=newer))
    await repo.session.commit()
    rows = await repo.list_for_document("doc-1")
    assert [r.id for r in rows] == ["b", "a"]


@pytest.mark.asyncio
async def test_list_for_document_bloom_filter(repo: FlashcardRepo) -> None:
    repo.session.add(_make_card(id="x", bloom_level=2))
    repo.session.add(_make_card(id="y", bloom_level=4))
    repo.session.add(_make_card(id="z", bloom_level=None))
    await repo.session.commit()
    rows = await repo.list_for_document("doc-1", bloom_level_min=3)
    assert {r.id for r in rows} == {"y"}


@pytest.mark.asyncio
async def test_list_for_section_join(repo: FlashcardRepo) -> None:
    repo.session.add(
        ChunkModel(
            id="c1",
            document_id="doc-1",
            section_id="sec-1",
            text="hello",
            chunk_index=0,
        )
    )
    repo.session.add(
        ChunkModel(
            id="c2",
            document_id="doc-1",
            section_id="sec-2",
            text="world",
            chunk_index=1,
        )
    )
    repo.session.add(_make_card(id="card-a", chunk_id="c1"))
    repo.session.add(_make_card(id="card-b", chunk_id="c2"))
    await repo.session.commit()
    rows = await repo.list_for_section("doc-1", "sec-1")
    assert [(c.id, sid) for c, sid in rows] == [("card-a", "sec-1")]


@pytest.mark.asyncio
async def test_list_existing_ids_in(repo: FlashcardRepo) -> None:
    repo.session.add(_make_card(id="a"))
    repo.session.add(_make_card(id="b"))
    await repo.session.commit()
    ids = await repo.list_existing_ids_in(["a", "missing", "b"])
    assert set(ids) == {"a", "b"}
    assert await repo.list_existing_ids_in([]) == []


@pytest.mark.asyncio
async def test_list_ids_for_document(repo: FlashcardRepo) -> None:
    repo.session.add(_make_card(id="a", document_id="d1"))
    repo.session.add(_make_card(id="b", document_id="d2"))
    await repo.session.commit()
    assert set(await repo.list_ids_for_document("d1")) == {"a"}


@pytest.mark.asyncio
async def test_delete_lifecycle(repo: FlashcardRepo) -> None:
    repo.session.add(_make_card(id="a"))
    repo.session.add(_make_card(id="b"))
    repo.session.add(_make_card(id="c"))
    await repo.session.commit()

    await repo.delete_by_id("a")
    assert set(await repo.list_ids_for_document("doc-1")) == {"b", "c"}

    await repo.delete_by_ids(["b", "c"])
    assert await repo.list_ids_for_document("doc-1") == []


@pytest.mark.asyncio
async def test_delete_for_document(repo: FlashcardRepo) -> None:
    repo.session.add(_make_card(id="a", document_id="d1"))
    repo.session.add(_make_card(id="b", document_id="d2"))
    await repo.session.commit()
    await repo.delete_for_document("d1")
    assert await repo.list_ids_for_document("d1") == []
    assert await repo.list_ids_for_document("d2") == ["b"]
