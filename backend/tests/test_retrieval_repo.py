"""RetrievalRepo, the retriever's SQLite reads (0.17.0 batch 1), on a real database."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.repos.document_repo import index_chunks_fts
from app.repos.retrieval_repo import RetrievalRepo
from tests.factories import make_chunk, make_document


@pytest.fixture
async def session(memory_db):
    factory = async_sessionmaker(memory_db.engine, expire_on_commit=False)
    async with factory() as s:
        for doc_id in ("d1", "d2"):
            s.add(make_document(id=doc_id, title=doc_id, file_path="/x", stage="parsing"))
        s.add_all(
            make_chunk(
                id=f"{doc_id}-c{i}",
                document_id=doc_id,
                text=f"morlocks chunk {i}" if doc_id == "d1" else "eloi only",
                token_count=3,
                page_number=i,
                chunk_index=i,
                speaker="HOST" if i == 1 else None,
                entry_date=date(2026, 7, i + 1) if i < 2 else None,
            )
            for doc_id in ("d1", "d2")
            for i in range(4)
        )
        await s.flush()
        for doc_id in ("d1", "d2"):
            await index_chunks_fts(s, doc_id)
        await s.execute(
            text(
                "INSERT INTO images_fts(image_id, document_id, body) "
                "VALUES ('i1', 'd1', 'a diagram of morlocks'), ('i2', 'd2', 'a diagram of eloi')"
            )
        )
        await s.commit()
        yield s


async def test_fts_chunks_scope_and_bm25_order(session):
    repo = RetrievalRepo(session)

    everywhere = await repo.fts_chunks("morlocks", None, 10)
    scoped = await repo.fts_chunks("eloi", ["d1"], 10)

    assert {r.document_id for r in everywhere} == {"d1"} and len(everywhere) == 4
    assert [r.score for r in everywhere] == sorted(r.score for r in everywhere)
    assert scoped == []


async def test_chunk_lookups(session):
    repo = RetrievalRepo(session)

    assert await repo.speakers_and_indexes(["d1-c0", "d1-c1"]) == {
        "d1-c0": (None, 0),
        "d1-c1": ("HOST", 1),
    }
    dates = dict(await repo.entry_dates(["d1-c0", "d1-c3"]))
    assert str(dates["d1-c0"]).startswith("2026-07-01") and dates["d1-c3"] is None
    window = await repo.chunk_window("d1", 1, 2)
    assert [(r.id, r.chunk_index, r.page_number, r.speaker) for r in window] == [
        ("d1-c1", 1, 1, "HOST"),
        ("d1-c2", 2, 2, None),
    ]


async def test_image_fts_ids_are_scoped(session):
    repo = RetrievalRepo(session)

    assert sorted(await repo.image_fts_ids("diagram", None, 5)) == ["i1", "i2"]
    assert await repo.image_fts_ids("diagram", ["d2"], 5) == ["i2"]
