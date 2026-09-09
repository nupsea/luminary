"""Knowing whether a document has anything left to be questioned on.

The reader's Practice face offered "add more questions" unconditionally and then
explained itself with an error when nothing came back. The error was honest and
the button was not: generation reads one passage, and on a deck that already
covers that passage the near-duplicate filter removes every question it produces
(`_passage_not_yet_used`). Two things follow, and both are tested here.

  1. GET /flashcards/{id}/headroom says what is left, so the button can be
     absent rather than apologetic.
  2. POST /flashcards/generate with avoid_used_material reads the chunks no card
     was written from -- without which a second "add more" re-reads the first
     passage for ever and can only produce duplicates.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, FlashcardModel, SectionModel


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

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


NOW = datetime.now(UTC)


async def _library(factory, *, chunks: int, used: list[int], section_split: int | None = None):
    """A document of `chunks` chunks, with a card written from each index in `used`."""
    doc_id = str(uuid.uuid4())
    section_a, section_b = str(uuid.uuid4()), str(uuid.uuid4())
    chunk_ids: list[str] = []
    async with factory() as s:
        s.add(DocumentModel(
            id=doc_id, title="Linear Programming", format="txt",
            content_type="notes", created_at=NOW, file_path=f"/tmp/{doc_id}.txt"))
        for name, sid in (("One", section_a), ("Two", section_b)):
            s.add(SectionModel(
                id=sid, document_id=doc_id, heading=name, level=1,
                section_order=0 if name == "One" else 1))
        for i in range(chunks):
            cid = str(uuid.uuid4())
            chunk_ids.append(cid)
            in_b = section_split is not None and i >= section_split
            s.add(ChunkModel(
                id=cid, document_id=doc_id, chunk_index=i,
                text=f"Passage {i} about vertices and feasible regions.",
                section_id=section_b if in_b else section_a))
        for i in used:
            s.add(FlashcardModel(
                id=str(uuid.uuid4()), document_id=doc_id, chunk_id=chunk_ids[i],
                question=f"Q about passage {i}?", answer="A.",
                source_excerpt="Passage.", fsrs_state="new", fsrs_stability=0.0,
                fsrs_difficulty=0.0, due_date=NOW, reps=0, lapses=0, created_at=NOW,
                source_chunk_ids=[chunk_ids[i]]))
        await s.commit()
    return doc_id, chunk_ids, section_a, section_b


async def test_headroom_counts_the_passages_no_card_was_written_from(test_db):
    _engine, factory, _tmp = test_db
    doc_id, _cids, _a, _b = await _library(factory, chunks=5, used=[0, 1])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/flashcards/{doc_id}/headroom")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "total_chunks": 5,
        "used_chunks": 2,
        "unused_chunks": 3,
        "cards": 2,
        "cards_without_sources": 0,
    }


async def test_headroom_is_zero_when_every_passage_has_a_card(test_db):
    """The state the panel must not offer to add more in."""
    _engine, factory, _tmp = test_db
    doc_id, _cids, _a, _b = await _library(factory, chunks=3, used=[0, 1, 2])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get(f"/flashcards/{doc_id}/headroom")).json()

    assert body["unused_chunks"] == 0
    assert body["used_chunks"] == 3


async def test_headroom_is_scoped_to_a_section(test_db):
    """A chapter can be exhausted while the book is not."""
    _engine, factory, _tmp = test_db
    doc_id, _cids, section_a, section_b = await _library(
        factory, chunks=4, used=[0, 1], section_split=2)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = (await client.get(
            f"/flashcards/{doc_id}/headroom", params={"section_id": section_a})).json()
        second = (await client.get(
            f"/flashcards/{doc_id}/headroom", params={"section_id": section_b})).json()

    assert first["unused_chunks"] == 0, "section one's two passages both have cards"
    assert second["unused_chunks"] == 2, "section two has none"


async def test_a_card_that_names_no_passage_is_reported_not_counted(test_db):
    """Cards predating source_chunk_ids. The headroom may over-state what is
    left -- it must never under-state it and hide a button that would work."""
    _engine, factory, _tmp = test_db
    doc_id, chunk_ids, _a, _b = await _library(factory, chunks=3, used=[0])
    async with factory() as s:
        s.add(FlashcardModel(
            id=str(uuid.uuid4()), document_id=doc_id, chunk_id=chunk_ids[1],
            question="Legacy card?", answer="A.", source_excerpt="Passage.",
            fsrs_state="new", fsrs_stability=0.0, fsrs_difficulty=0.0,
            due_date=NOW, reps=0, lapses=0, created_at=NOW, source_chunk_ids=None))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get(f"/flashcards/{doc_id}/headroom")).json()

    assert body["cards"] == 2
    assert body["cards_without_sources"] == 1
    assert body["unused_chunks"] == 2, "the legacy card claims no passage"


async def test_generate_reads_unused_material_when_asked(test_db):
    """Without this the second "add more" re-reads the first passage for ever,
    and the near-duplicate filter removes everything it writes."""
    _engine, factory, _tmp = test_db
    doc_id, chunk_ids, _a, _b = await _library(factory, chunks=4, used=[0, 1])

    seen: dict = {}

    async def _capture(*args, **kwargs):
        seen["exclude"] = kwargs.get("exclude_chunk_ids")
        return []

    stub = AsyncMock(side_effect=_capture)
    with patch("app.services.flashcard.FlashcardService.generate", new=stub):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/flashcards/generate", json={
                "document_id": doc_id, "count": 3, "avoid_used_material": True})

    assert resp.status_code == 201, resp.text
    assert seen["exclude"] == {chunk_ids[0], chunk_ids[1]}


async def test_generate_reads_the_selection_when_one_is_given(test_db):
    """A selection IS the passage. Excluding used chunks there would silently
    refuse to make a card about text the reader just highlighted."""
    _engine, factory, _tmp = test_db
    doc_id, _cids, _a, _b = await _library(factory, chunks=4, used=[0, 1])

    seen: dict = {}

    async def _capture(*args, **kwargs):
        seen["exclude"] = kwargs.get("exclude_chunk_ids")
        return []

    stub = AsyncMock(side_effect=_capture)
    with patch("app.services.flashcard.FlashcardService.generate", new=stub):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/flashcards/generate", json={
                "document_id": doc_id, "count": 1, "avoid_used_material": True,
                "context": "A vertex of the feasible region carries the optimum."})

    assert resp.status_code == 201, resp.text
    assert seen["exclude"] is None


async def test_generate_leaves_other_callers_alone(test_db):
    """The flag is opt-in: every existing caller keeps reading the passage its
    scope names."""
    _engine, factory, _tmp = test_db
    doc_id, _cids, _a, _b = await _library(factory, chunks=4, used=[0, 1])

    seen: dict = {}

    async def _capture(*args, **kwargs):
        seen["exclude"] = kwargs.get("exclude_chunk_ids")
        return []

    stub = AsyncMock(side_effect=_capture)
    with patch("app.services.flashcard.FlashcardService.generate", new=stub):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/flashcards/generate", json={
                "document_id": doc_id, "count": 3})

    assert resp.status_code == 201, resp.text
    assert seen["exclude"] is None
