"""Deleting a card is a decision about every table that points at it.

`bulk-delete` removed the card and its FTS row and nothing else, so a table
keyed on `flashcard_id` was left holding rows about a card that no longer
exists -- the same omission that left 3,250 orphans behind deleted documents.
The list is derived from the models here so the next such table fails this test
until someone says which it is: cascaded, or learner record that outlives the
card.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import Base, FlashcardModel, MisconceptionModel, ReviewEventModel
from app.repos.flashcard_repo import _CARD_CHILD_TABLES, FlashcardRepo

# Records what the learner did rather than what the card said. Deleting a card
# must not rewrite the history of the days it was studied.
_CARD_LEARNER_RECORD_TABLES = (ReviewEventModel,)


def _models_with_flashcard_id() -> set[type]:
    return {
        cls
        for cls in Base.__subclasses__()
        if getattr(cls, "__tablename__", None) is not None
        and "flashcard_id" in cls.__table__.columns
    }


def test_every_card_scoped_table_is_cascaded_or_declared():
    accounted = set(_CARD_CHILD_TABLES) | set(_CARD_LEARNER_RECORD_TABLES)
    unaccounted = {cls.__tablename__ for cls in _models_with_flashcard_id() - accounted}
    assert not unaccounted, (
        f"tables carry a flashcard_id but deleting a card ignores them: "
        f"{sorted(unaccounted)}. Add each to _CARD_CHILD_TABLES, or to this test's "
        f"learner-record list if its rows should outlive the card."
    )


def test_the_two_lists_do_not_overlap():
    assert not set(_CARD_CHILD_TABLES) & set(_CARD_LEARNER_RECORD_TABLES)


@pytest.fixture()
async def factory(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'cards.db'}")
    await create_all_tables(engine)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_deleting_a_card_takes_its_misconception_with_it(factory):
    card_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            FlashcardModel(
                id=card_id,
                document_id="doc-1",
                question="q",
                answer="a",
                source_excerpt="",
                difficulty="medium",
                fsrs_state="new",
                fsrs_stability=0.0,
                fsrs_difficulty=0.0,
                reps=0,
                lapses=0,
            )
        )
        session.add(
            MisconceptionModel(
                id=str(uuid.uuid4()),
                document_id="doc-1",
                flashcard_id=card_id,
                user_answer="wrong",
                error_type="misconception",
                correction_note="note",
            )
        )
        await session.commit()

        await FlashcardRepo(session).delete_by_ids([card_id])

        left = (
            await session.execute(
                select(MisconceptionModel).where(MisconceptionModel.flashcard_id == card_id)
            )
        ).scalars().all()
    assert left == [], "a correction note against a deleted card is unreadable"


@pytest.mark.asyncio
async def test_deleting_a_card_keeps_the_review_that_happened(factory):
    """The streak is a fact about the learner, not about the card."""
    card_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            FlashcardModel(
                id=card_id,
                document_id="doc-1",
                question="q",
                answer="a",
                source_excerpt="",
                difficulty="medium",
                fsrs_state="new",
                fsrs_stability=0.0,
                fsrs_difficulty=0.0,
                reps=1,
                lapses=0,
            )
        )
        session.add(
            ReviewEventModel(
                id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()),
                flashcard_id=card_id,
                rating="good",
                is_correct=True,
            )
        )
        await session.commit()

        await FlashcardRepo(session).delete_by_ids([card_id])

        kept = (
            await session.execute(
                select(ReviewEventModel).where(ReviewEventModel.flashcard_id == card_id)
            )
        ).scalars().all()
    assert len(kept) == 1, "deleting a card must not erase the day it was studied"
