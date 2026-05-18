"""Unit tests for DocumentRepo (audit #9 fan-out)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import (
    ChunkModel,
    DocumentModel,
    ReadingProgressModel,
    SectionModel,
)
from app.repos.document_repo import DocumentRepo


@pytest.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield DocumentRepo(session)
    await engine.dispose()


def _make_doc(*, id: str = "d1", title: str = "T", file_hash: str | None = None) -> DocumentModel:
    return DocumentModel(
        id=id,
        title=title,
        format="pdf",
        content_type="book",
        file_path=f"/tmp/{id}",
        file_hash=file_hash,
        stage="complete",
        tags=[],
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_get_or_404(repo: DocumentRepo) -> None:
    repo.session.add(_make_doc(id="d1"))
    await repo.session.commit()
    doc = await repo.get_or_404("d1")
    assert doc.id == "d1"
    with pytest.raises(HTTPException) as ei:
        await repo.get_or_404("nope")
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_find_by_file_hash(repo: DocumentRepo) -> None:
    repo.session.add(_make_doc(id="d1", file_hash="abc"))
    repo.session.add(_make_doc(id="d2", file_hash=None))
    await repo.session.commit()
    found = await repo.find_by_file_hash("abc")
    assert found is not None and found.id == "d1"
    assert await repo.find_by_file_hash("nope") is None


@pytest.mark.asyncio
async def test_sections_for_document_orders_by_order(repo: DocumentRepo) -> None:
    repo.session.add(_make_doc(id="d1"))
    repo.session.add(
        SectionModel(id="s2", document_id="d1", heading="B", level=1, section_order=2)
    )
    repo.session.add(
        SectionModel(id="s1", document_id="d1", heading="A", level=1, section_order=1)
    )
    await repo.session.commit()
    sections = await repo.sections_for_document("d1")
    assert [s.id for s in sections] == ["s1", "s2"]


@pytest.mark.asyncio
async def test_chunks_for_document_orders_by_index(repo: DocumentRepo) -> None:
    repo.session.add(_make_doc(id="d1"))
    repo.session.add(
        ChunkModel(id="c2", document_id="d1", text="b", chunk_index=2)
    )
    repo.session.add(
        ChunkModel(id="c1", document_id="d1", text="a", chunk_index=1)
    )
    await repo.session.commit()
    chunks = await repo.chunks_for_document("d1")
    assert [c.id for c in chunks] == ["c1", "c2"]


@pytest.mark.asyncio
async def test_read_section_count(repo: DocumentRepo) -> None:
    repo.session.add(_make_doc(id="d1"))
    assert await repo.read_section_count("d1") == 0
    repo.session.add(
        ReadingProgressModel(
            id="r1",
            document_id="d1",
            section_id="s1",
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
        )
    )
    repo.session.add(
        ReadingProgressModel(
            id="r2",
            document_id="d1",
            section_id="s2",
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
        )
    )
    await repo.session.commit()
    assert await repo.read_section_count("d1") == 2
