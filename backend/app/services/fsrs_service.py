"""FSRS spaced-repetition scheduling service.

Uses fsrs v6 (Scheduler) to update card stability, difficulty, due date,
and state after each review. Tracks reps and lapses manually since fsrs v6
Card no longer exposes those fields.
"""

import logging
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FlashcardModel

logger = logging.getLogger(__name__)

RATING_MAP: dict[str, int] = {
    "again": 1,  # Rating.Again
    "hard": 2,   # Rating.Hard
    "good": 3,   # Rating.Good
    "easy": 4,   # Rating.Easy
}

# fsrs v6 State enum values: Learning=1, Review=2, Relearning=3
_STATE_INT_TO_STR: dict[int, str] = {
    1: "learning",
    2: "review",
    3: "relearning",
}

_STATE_STR_TO_INT: dict[str, int] = {
    "new": 1,
    "learning": 1,
    "review": 2,
    "relearning": 3,
}


class FSRSService:
    """Schedules flashcard reviews using the FSRS algorithm."""

    def _build_fsrs_card(self, db_card: FlashcardModel):  # type: ignore[return]
        from fsrs import Card  # noqa: PLC0415

        card_id = abs(hash(db_card.id)) % (10**12)
        stability = db_card.fsrs_stability if db_card.fsrs_stability else None
        difficulty = db_card.fsrs_difficulty if db_card.fsrs_difficulty else None

        due_str = (
            db_card.due_date.replace(tzinfo=UTC).isoformat()
            if db_card.due_date
            else datetime.now(UTC).isoformat()
        )
        last_review_str = (
            db_card.last_review.replace(tzinfo=UTC).isoformat()
            if db_card.last_review
            else None
        )

        return Card.from_dict(
            {
                "card_id": card_id,
                "state": _STATE_STR_TO_INT.get(db_card.fsrs_state, 1),
                "step": 0,
                "stability": stability,
                "difficulty": difficulty,
                "due": due_str,
                "last_review": last_review_str,
            }
        )

    async def schedule(
        self,
        card_id: str,
        rating: Literal["again", "hard", "good", "easy"],
        session: AsyncSession,
    ) -> FlashcardModel:
        """Apply an FSRS review and persist the updated card state."""
        from fsrs import Rating, Scheduler  # noqa: PLC0415

        result = await session.execute(
            select(FlashcardModel).where(FlashcardModel.id == card_id)
        )
        db_card = result.scalar_one_or_none()
        if db_card is None:
            raise ValueError(f"Flashcard {card_id} not found")

        fsrs_card = self._build_fsrs_card(db_card)
        rating_enum = Rating(RATING_MAP[rating])

        sched = Scheduler()
        now = datetime.now(UTC)
        updated_card, _ = sched.review_card(fsrs_card, rating_enum, now)

        # Update persisted fields — reps/lapses tracked manually
        db_card.fsrs_stability = updated_card.stability or 0.0
        db_card.fsrs_difficulty = updated_card.difficulty or 0.0
        # Store as naive datetime (SQLite has no timezone support)
        if updated_card.due:
            db_card.due_date = updated_card.due.replace(tzinfo=None)
        state_val = (
            updated_card.state.value
            if hasattr(updated_card.state, "value")
            else int(updated_card.state)
        )
        db_card.fsrs_state = _STATE_INT_TO_STR.get(state_val, "learning")
        db_card.last_review = now.replace(tzinfo=None)
        db_card.reps = (db_card.reps or 0) + 1
        if rating == "again":
            db_card.lapses = (db_card.lapses or 0) + 1

        await session.commit()
        await session.refresh(db_card)
        logger.info(
            "Flashcard reviewed",
            extra={"card_id": card_id, "rating": rating, "new_state": db_card.fsrs_state},
        )
        return db_card


_fsrs_service: FSRSService | None = None


def get_fsrs_service() -> FSRSService:
    global _fsrs_service  # noqa: PLW0603
    if _fsrs_service is None:
        _fsrs_service = FSRSService()
    return _fsrs_service
