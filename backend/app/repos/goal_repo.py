"""Learning goals, the Pomodoro sessions linked to them, and what happened inside those sessions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FlashcardModel,
    LearningGoalModel,
    NoteModel,
    PomodoroSessionModel,
    QAHistoryModel,
    ReviewEventModel,
)


class GoalRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- goals -------------------------------------------------------------

    async def find(self, goal_id: str) -> LearningGoalModel | None:
        result = await self.session.execute(
            select(LearningGoalModel).where(LearningGoalModel.id == goal_id)
        )
        return result.scalar_one_or_none()

    async def list_newest_first(self, status: str | None) -> list[LearningGoalModel]:
        stmt = select(LearningGoalModel).order_by(LearningGoalModel.created_at.desc())
        if status is not None:
            stmt = stmt.where(LearningGoalModel.status == status)
        return list((await self.session.execute(stmt)).scalars().all())

    # -- linked sessions ---------------------------------------------------

    async def find_session(self, session_id: str) -> PomodoroSessionModel | None:
        result = await self.session.execute(
            select(PomodoroSessionModel).where(PomodoroSessionModel.id == session_id)
        )
        return result.scalar_one_or_none()

    async def unlink_all_sessions(self, goal_id: str) -> None:
        """Uncommitted: SQLite cannot add the FK, so this is its ON DELETE SET NULL."""
        await self.session.execute(
            update(PomodoroSessionModel)
            .where(PomodoroSessionModel.goal_id == goal_id)
            .values(goal_id=None)
        )

    async def linked_sessions(self, goal_id: str, limit: int) -> list[PomodoroSessionModel]:
        result = await self.session.execute(
            select(PomodoroSessionModel)
            .where(PomodoroSessionModel.goal_id == goal_id)
            .order_by(PomodoroSessionModel.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def completed_sessions(
        self, goal_id: str, surfaces: list[str] | None = None
    ) -> list[PomodoroSessionModel]:
        """Completed sessions linked to the goal; `surfaces` None means any surface."""
        stmt = select(PomodoroSessionModel).where(
            PomodoroSessionModel.goal_id == goal_id,
            PomodoroSessionModel.status == "completed",
        )
        if surfaces is not None:
            stmt = stmt.where(PomodoroSessionModel.surface.in_(surfaces))
        return list((await self.session.execute(stmt)).scalars().all())

    # -- activity inside a session window ----------------------------------

    async def reviews_between(self, start: datetime, end: datetime) -> list[ReviewEventModel]:
        result = await self.session.execute(
            select(ReviewEventModel).where(
                ReviewEventModel.reviewed_at >= start,
                ReviewEventModel.reviewed_at <= end,
            )
        )
        return list(result.scalars().all())

    async def deck_card_ids(self, deck: str) -> set[str]:
        result = await self.session.execute(
            select(FlashcardModel.id).where(FlashcardModel.deck == deck)
        )
        return set(result.scalars().all())

    async def count_notes_between(self, start: datetime, end: datetime) -> int:
        result = await self.session.execute(
            select(func.count(NoteModel.id)).where(
                NoteModel.created_at >= start, NoteModel.created_at <= end
            )
        )
        return int(result.scalar_one())

    async def count_qa_turns_between(self, start: datetime, end: datetime) -> int:
        result = await self.session.execute(
            select(func.count(QAHistoryModel.id)).where(
                QAHistoryModel.created_at >= start, QAHistoryModel.created_at <= end
            )
        )
        return int(result.scalar_one())
