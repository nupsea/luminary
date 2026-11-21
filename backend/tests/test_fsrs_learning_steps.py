"""A learning card graduates on Good: the scheduler's step is stored, not rebuilt as 0 (#533).

fsrs 6 graduates a learning card only when `step + 1 == len(learning_steps)`. Its default
scheduler has two learning steps and one relearning step, so a card rebuilt at step 0 every
review moved 0 -> 1 on each Good and never reached `review`.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.db_init import init_database
from app.models import FlashcardModel, ReviewEventModel
from app.services.fsrs_service import FSRSService
from tests.factories import make_card
from tests.test_drop_content_type_migration import _migrate

pytestmark = pytest.mark.usefixtures("card_documents")

BEFORE_STEP = "7f6bcd0f8881"


def _card(**kwargs) -> FlashcardModel:
    defaults = {"due_date": datetime.now(UTC) - timedelta(seconds=10)}
    return make_card(id=str(uuid.uuid4()), document_id=str(uuid.uuid4()), **{**defaults, **kwargs})


async def _review(factory, card_id: str, *ratings: str) -> list[tuple[str, int | None]]:
    seen = []
    for rating in ratings:
        async with factory() as session:
            card = await FSRSService().schedule(card_id, rating, session)
            seen.append((card.fsrs_state, card.fsrs_step))
    return seen


async def test_a_new_card_reaches_review_on_good_good(memory_db):
    card = _card(fsrs_state="new")
    async with memory_db.factory() as session:
        session.add(card)
        await session.commit()

    assert await _review(memory_db.factory, card.id, "good", "good") == [
        ("learning", 1),
        ("review", None),
    ]


async def test_a_lapsed_review_card_returns_to_review(memory_db):
    """A regression pin, not evidence of the fix: fsrs has one relearning step, so Good
    graduates a relearning card even at a hard-coded step 0. It fails on the old code only
    because a review card then stored step 0, not None."""
    card = _card(fsrs_state="new")
    async with memory_db.factory() as session:
        session.add(card)
        await session.commit()
    await _review(memory_db.factory, card.id, "easy")

    assert await _review(memory_db.factory, card.id, "again", "good", "good") == [
        ("relearning", 0),
        ("review", None),
        ("review", None),
    ]


async def test_hard_keeps_a_learning_card_on_its_step(memory_db):
    card = _card(fsrs_state="learning", fsrs_step=1, fsrs_stability=2.3, fsrs_difficulty=5.0)
    async with memory_db.factory() as session:
        session.add(card)
        await session.commit()

    assert await _review(memory_db.factory, card.id, "hard", "good") == [
        ("learning", 1),
        ("review", None),
    ]


def _event(card_id: str, rating: str, at: datetime) -> ReviewEventModel:
    return ReviewEventModel(
        id=str(uuid.uuid4()),
        session_id="s",
        flashcard_id=card_id,
        rating=rating,
        is_correct=rating != "again",
        reviewed_at=at,
    )


async def test_the_upgrade_infers_the_step_and_moves_no_due_date(memory_db):
    reviewed = datetime(2026, 11, 20, 9, 0, 0)
    due = datetime(2026, 11, 20, 9, 10, 0)
    cards = {
        # A Good under the old code left the scheduler at step 1.
        "good": _card(fsrs_state="learning", last_review=reviewed, due_date=due),
        "again": _card(fsrs_state="learning", last_review=reviewed, due_date=due),
        "hard": _card(fsrs_state="learning", last_review=reviewed, due_date=due),
        # The newest event is an older review (the last one was made outside a session).
        "stale": _card(fsrs_state="learning", last_review=reviewed, due_date=due),
        # A Good 30 s after the last review is another review: past the 5 s window.
        "near": _card(fsrs_state="learning", last_review=reviewed, due_date=due),
        "no_event": _card(fsrs_state="learning", last_review=reviewed, due_date=due),
        "relearning": _card(fsrs_state="relearning", last_review=reviewed, due_date=due),
        "review": _card(fsrs_state="review", last_review=reviewed, due_date=due + timedelta(3)),
        "new": _card(fsrs_state="new", due_date=due),
    }
    await init_database(memory_db.engine)  # the shared template is built from the models
    async with memory_db.factory() as session:
        session.add_all(cards.values())
        session.add_all(
            [
                _event(cards["good"].id, "good", reviewed + timedelta(milliseconds=40)),
                _event(cards["again"].id, "again", reviewed + timedelta(milliseconds=40)),
                _event(cards["hard"].id, "hard", reviewed + timedelta(milliseconds=40)),
                _event(cards["stale"].id, "good", reviewed - timedelta(hours=2)),
                _event(cards["near"].id, "good", reviewed + timedelta(seconds=30)),
                _event(cards["relearning"].id, "good", reviewed + timedelta(milliseconds=40)),
            ]
        )
        await session.commit()
    before = {name: card.due_date for name, card in cards.items()}

    await _migrate(memory_db.engine, BEFORE_STEP)
    async with memory_db.engine.begin() as conn:
        columns = (await conn.execute(text("PRAGMA table_info(flashcards)"))).fetchall()
        assert "fsrs_step" not in {c[1] for c in columns}
    await init_database(memory_db.engine)

    async with memory_db.factory() as session:
        rows = {c.id: c for c in (await session.execute(select(FlashcardModel))).scalars()}
    after = {name: rows[card.id] for name, card in cards.items()}
    assert {name: card.due_date for name, card in after.items()} == before
    assert {name: card.fsrs_step for name, card in after.items()} == {
        "good": 1,
        "again": 0,
        "hard": 0,
        "stale": 0,
        "near": 0,
        "no_event": 0,
        "relearning": 0,
        "review": None,
        "new": None,
    }

    # The card the old code held at step 1 graduates on its next Good.
    assert await _review(memory_db.factory, cards["good"].id, "good") == [("review", None)]
