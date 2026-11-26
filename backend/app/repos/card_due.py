"""The two ways a card enters a session: a scheduled review that has come due, or an unseen card.

Every count and queue reads these, so "due" means the same thing on every surface (I-83).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_

from app.models import FlashcardModel
from app.types import CARD_NEW, SCHEDULED_STATES


def review_due(now: datetime):  # type: ignore[no-untyped-def]
    return and_(
        FlashcardModel.fsrs_state.in_(SCHEDULED_STATES),
        FlashcardModel.due_date.is_not(None),
        FlashcardModel.due_date <= now,
    )


def unseen(now: datetime):  # type: ignore[no-untyped-def]
    """Never reviewed, and not put off to a later date."""
    return and_(
        FlashcardModel.fsrs_state == CARD_NEW,
        or_(FlashcardModel.due_date.is_(None), FlashcardModel.due_date <= now),
    )
