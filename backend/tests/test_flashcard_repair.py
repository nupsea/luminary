"""The search index and the card-scoped tables have to agree with the cards.

Three defects produced drift no user action could clear, and a real library was
carrying all three: 228 index rows named a deleted card, 71 child rows named one,
and 1 card had never been indexed at all, so no query could find it.

Repair is deterministic and deletes no flashcard. `review_events` is deliberately
untouched -- an event with no card is the record of a review that happened.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import (
    DocumentModel,
    FlashcardModel,
    MisconceptionModel,
    ReviewEventModel,
)
from app.services.document_deletion_service import DocumentDeletionService


@pytest.fixture()
async def test_db(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'repair.db'}")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_session_factory", factory)
    yield factory
    await engine.dispose()


def _card(card_id: str, doc_id: str | None = "doc-1") -> FlashcardModel:
    return FlashcardModel(
        id=card_id,
        document_id=doc_id,
        question="How did Penelope delay the suitors?",
        answer="She unravelled her weaving each night.",
        source_excerpt="",
        difficulty="medium",
        fsrs_state="new",
        fsrs_stability=0.0,
        fsrs_difficulty=0.0,
        reps=0,
        lapses=0,
    )


async def _index_count(session, card_id: str) -> int:
    row = await session.execute(
        text("SELECT COUNT(*) FROM flashcards_fts_content WHERE c2 = :fid"),
        {"fid": card_id},
    )
    return row.scalar_one()


@pytest.mark.asyncio
async def test_repair_drops_index_rows_for_cards_that_are_gone(test_db):
    ghost = str(uuid.uuid4())
    async with test_db() as session:
        await session.execute(
            text(
                "INSERT INTO flashcards_fts(flashcard_id, question, answer) "
                "VALUES (:fid, 'ghost question', 'ghost answer')"
            ),
            {"fid": ghost},
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/flashcards/repair")

    assert resp.status_code == 200, resp.text
    assert resp.json()["index_rows_removed"] == 1
    async with test_db() as session:
        assert await _index_count(session, ghost) == 0


@pytest.mark.asyncio
async def test_repair_indexes_a_card_that_was_never_indexed(test_db):
    """A card inserted without indexing exists and cannot be found."""
    card_id = str(uuid.uuid4())
    async with test_db() as session:
        session.add(_card(card_id))
        await session.commit()
        assert await _index_count(session, card_id) == 0

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/flashcards/repair")

    assert resp.json()["cards_indexed"] == 1
    async with test_db() as session:
        assert await _index_count(session, card_id) == 1


@pytest.mark.asyncio
async def test_repair_drops_orphan_child_rows_but_keeps_the_review_record(test_db):
    gone = str(uuid.uuid4())
    async with test_db() as session:
        session.add(
            MisconceptionModel(
                id=str(uuid.uuid4()),
                document_id="doc-1",
                flashcard_id=gone,
                user_answer="wrong",
                error_type="misconception",
                correction_note="note",
            )
        )
        session.add(
            ReviewEventModel(
                id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()),
                flashcard_id=gone,
                rating="good",
                is_correct=True,
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/flashcards/repair")

    assert resp.json()["orphan_rows_removed"] == 1
    async with test_db() as session:
        kept = (await session.execute(select(ReviewEventModel))).scalars().all()
    assert len(kept) == 1, "a review that happened is not repaired away"


@pytest.mark.asyncio
async def test_repair_is_idempotent(test_db):
    card_id = str(uuid.uuid4())
    async with test_db() as session:
        session.add(_card(card_id))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/flashcards/repair")
        second = (await c.post("/flashcards/repair")).json()

    assert second == {
        "index_rows_removed": 0,
        "cards_indexed": 0,
        "orphan_rows_removed": 0,
    }


@pytest.mark.asyncio
async def test_deleting_a_document_clears_its_cards_from_the_index(test_db):
    """`flashcards_fts` has no document_id, so the cascade has to read the card ids.

    Missing this is what left 228 index rows pointing at cards that no longer
    existed -- and flashcard search matches the index, so those cards kept coming
    back in results after their document was deleted.
    """
    doc_id = str(uuid.uuid4())
    card_id = str(uuid.uuid4())
    async with test_db() as session:
        doc = DocumentModel(
            id=doc_id,
            title="the_odyssey",
            format="txt",
            content_type="book",
            word_count=100,
            page_count=1,
            file_path="/tmp/the_odyssey.txt",
            stage="complete",
            tags=[],
        )
        session.add(doc)
        session.add(_card(card_id, doc_id))
        await session.execute(
            text(
                "INSERT INTO flashcards_fts(flashcard_id, question, answer) "
                "VALUES (:fid, 'q', 'a')"
            ),
            {"fid": card_id},
        )
        await session.commit()

        await DocumentDeletionService().delete_sqlite_cascade(session, doc)
        await session.commit()

        assert await _index_count(session, card_id) == 0
