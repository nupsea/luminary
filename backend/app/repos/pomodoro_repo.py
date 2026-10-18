"""Pomodoro focus sessions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PomodoroSessionModel


class PomodoroRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find(self, session_id: str) -> PomodoroSessionModel | None:
        return await self.session.get(PomodoroSessionModel, session_id)

    async def in_status(self, statuses: Sequence[str]) -> PomodoroSessionModel | None:
        result = await self.session.execute(
            select(PomodoroSessionModel).where(PomodoroSessionModel.status.in_(list(statuses)))
        )
        return result.scalar_one_or_none()

    async def count_completed(self, since: datetime | None = None) -> int:
        stmt = select(func.count(PomodoroSessionModel.id)).where(
            PomodoroSessionModel.status == "completed"
        )
        if since is not None:
            stmt = stmt.where(PomodoroSessionModel.created_at >= since)
        return int((await self.session.execute(stmt)).scalar_one())

    async def completed_created_at(self) -> list[datetime]:
        result = await self.session.execute(
            select(PomodoroSessionModel.created_at).where(
                PomodoroSessionModel.status == "completed"
            )
        )
        return [ts for ts in result.scalars().all() if ts is not None]
