"""Backfilling `word_count` for documents ingested before it was persisted.

`d14adcd` added the write; every document ingested before it reads 0 while
holding a full set of chunks and sections. Zero is not cosmetic -- study slot
distribution weights sources by word count and skips a 0-weight one, which
`studyDistribute.test.ts` already carries a regression for.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import DocumentModel
from app.scripts.backfill_word_counts import recount_all


@pytest.fixture
async def library(tmp_path, monkeypatch):
    """An in-memory library plus a real source file on disk to recount from."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    yield tmp_path, factory
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    await engine.dispose()


async def _add(factory, **kwargs):
    defaults = {
        "format": "txt",
        "content_type": "book",
        "stage": "complete",
        "word_count": 0,
    }
    async with factory() as session:
        session.add(DocumentModel(**{**defaults, **kwargs}))
        await session.commit()


@pytest.mark.asyncio
async def test_a_zero_word_document_is_recounted_from_its_source(library):
    tmp_path, factory = library
    source = tmp_path / "book.txt"
    source.write_text("one two three four five six seven")
    await _add(factory, id="d1", title="book", file_path=str(source))

    results = await recount_all(apply=True)

    assert [(r.title, r.word_count, r.ok) for r in results] == [("book", 7, True)]
    async with factory() as session:
        doc = (await session.execute(select(DocumentModel))).scalars().one()
    assert doc.word_count == 7


@pytest.mark.asyncio
async def test_a_dry_run_writes_nothing(library):
    tmp_path, factory = library
    source = tmp_path / "book.txt"
    source.write_text("one two three")
    await _add(factory, id="d1", title="book", file_path=str(source))

    results = await recount_all(apply=False)

    assert results[0].word_count == 3
    async with factory() as session:
        doc = (await session.execute(select(DocumentModel))).scalars().one()
    assert doc.word_count == 0


@pytest.mark.asyncio
async def test_a_document_whose_source_is_gone_keeps_its_zero(library):
    """A number nobody can reproduce is worse than an obvious gap. Counting from
    chunks would be the tempting shortcut and is wrong: chunks overlap by
    construction (I-29), so summing across them overcounts every seam."""
    tmp_path, factory = library
    await _add(factory, id="d1", title="lost", file_path=str(tmp_path / "not-here.txt"))

    results = await recount_all(apply=True)

    assert results[0].ok is False
    assert "gone" in (results[0].reason or "")
    async with factory() as session:
        doc = (await session.execute(select(DocumentModel))).scalars().one()
    assert doc.word_count == 0


@pytest.mark.asyncio
async def test_a_document_that_already_has_a_count_is_left_alone(library):
    """The backfill closes a historical gap; it must never rewrite a count a
    real ingestion produced."""
    tmp_path, factory = library
    source = tmp_path / "book.txt"
    source.write_text("one two three")
    await _add(factory, id="d1", title="counted", file_path=str(source), word_count=999)

    results = await recount_all(apply=True)

    assert results == []
    async with factory() as session:
        doc = (await session.execute(select(DocumentModel))).scalars().one()
    assert doc.word_count == 999


@pytest.mark.asyncio
async def test_an_incomplete_ingestion_is_not_backfilled(library):
    """A document still being ingested has no final text to count, and writing
    one would present an interrupted ingest as a finished document."""
    tmp_path, factory = library
    source = tmp_path / "book.txt"
    source.write_text("one two three")
    await _add(factory, id="d1", title="midway", file_path=str(source), stage="embedding")

    assert await recount_all(apply=True) == []


@pytest.mark.asyncio
async def test_one_unreadable_file_does_not_stop_the_rest(library):
    tmp_path, factory = library
    good = tmp_path / "good.txt"
    good.write_text("one two three four")
    bad = tmp_path / "bad.txt"
    bad.write_text("")
    await _add(factory, id="d1", title="good", file_path=str(good))
    await _add(factory, id="d2", title="empty", file_path=str(bad))

    results = {r.title: r for r in await recount_all(apply=True)}

    assert results["good"].word_count == 4
    assert results["empty"].ok is False
