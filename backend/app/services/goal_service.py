"""GoalService -- learning goals with FSRS-based readiness projection.

The FSRS-4.5 power-law retrievability formula:

    R(t, S) = (1 + FACTOR * t / S) ^ DECAY

where:
    FACTOR = 19/81   (FSRS-4.5 constant)
    DECAY  = -0.5    (FSRS-4.5 constant)
    t      = days elapsed since last review + days remaining until target
    S      = fsrs_stability (in days)

A card with stability=0 (never reviewed) returns R=0.0 -- always at-risk.
"""

import logging
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FlashcardModel, LearningGoalModel

logger = logging.getLogger(__name__)

# FSRS-4.5 constants
_FACTOR: float = 19.0 / 81.0
_DECAY: float = -0.5


def _retrievability(stability: float, t: float) -> float:
    """Compute FSRS-4.5 retrievability for a card with given stability at time t (days).

    Returns a value in [0.0, 1.0].  Returns 0.0 for stability <= 0.
    """
    if stability <= 0 or t < 0:
        return 0.0
    return (1.0 + _FACTOR * t / stability) ** _DECAY


class GoalService:
    """Manages learning goals and computes readiness projections."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_goal(
        self, goal_id: str, document_id: str, title: str, target_date: str
    ) -> LearningGoalModel:
        goal = LearningGoalModel(
            id=goal_id,
            document_id=document_id,
            title=title,
            target_date=target_date,
        )
        self._session.add(goal)
        await self._session.commit()
        await self._session.refresh(goal)
        logger.info(
            "Created learning goal %s for document %s target=%s",
            goal_id,
            document_id,
            target_date,
        )
        return goal

    async def list_goals(self) -> list[LearningGoalModel]:
        result = await self._session.execute(
            select(LearningGoalModel).order_by(LearningGoalModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_goal(self, goal_id: str) -> LearningGoalModel | None:
        result = await self._session.execute(
            select(LearningGoalModel).where(LearningGoalModel.id == goal_id)
        )
        return result.scalar_one_or_none()

    async def delete_goal(self, goal_id: str) -> bool:
        goal = await self.get_goal(goal_id)
        if goal is None:
            return False
        await self._session.delete(goal)
        await self._session.commit()
        logger.info("Deleted learning goal %s", goal_id)
        return True

    async def compute_readiness(self, goal: LearningGoalModel) -> dict:
        """Project flashcard retention at target_date for the goal's document.

        Returns a dict with:
            on_track (bool)
            projected_retention_pct (float 0-100)
            at_risk_card_count (int)
            at_risk_cards (list[dict])
        """
        target = date.fromisoformat(goal.target_date)
        today = datetime.now(UTC).date()
        days_until_target = max((target - today).days, 0)

        result = await self._session.execute(
            select(FlashcardModel).where(FlashcardModel.document_id == goal.document_id)
        )
        cards = list(result.scalars().all())

        if not cards:
            return {
                "on_track": False,
                "projected_retention_pct": 0.0,
                "at_risk_card_count": 0,
                "at_risk_cards": [],
            }

        at_risk = []
        total_retention = 0.0

        for card in cards:
            if card.last_review is not None:
                last_review_date = card.last_review.date()
                days_since_review = (today - last_review_date).days
            else:
                days_since_review = 0

            t = days_since_review + days_until_target
            r = _retrievability(card.fsrs_stability, t)
            total_retention += r

            if r < 0.80:
                at_risk.append(
                    {
                        "id": card.id,
                        "question": card.question,
                        "projected_retention_pct": round(r * 100, 1),
                    }
                )

        projected_pct = round((total_retention / len(cards)) * 100, 1)
        at_risk.sort(key=lambda c: c["projected_retention_pct"])

        return {
            "on_track": projected_pct >= 80.0,
            "projected_retention_pct": projected_pct,
            "at_risk_card_count": len(at_risk),
            "at_risk_cards": at_risk,
        }
