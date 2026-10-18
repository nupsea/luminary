"""Foreground-attention intervals, one row per run of heartbeats."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TimeOnTaskModel


class TimeOnTaskRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest(self, activity: str, member_id: str | None) -> TimeOnTaskModel | None:
        """The most recently beaten interval for this activity and member."""
        result = await self.session.execute(
            select(TimeOnTaskModel)
            .where(
                TimeOnTaskModel.activity == activity,
                TimeOnTaskModel.member_id.is_(None)
                if member_id is None
                else TimeOnTaskModel.member_id == member_id,
            )
            .order_by(TimeOnTaskModel.last_beat_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def seconds_since(self, cutoff: datetime) -> list[tuple[str, int]]:
        """(activity, seconds) per interval that began at or after `cutoff`."""
        result = await self.session.execute(
            select(TimeOnTaskModel.activity, TimeOnTaskModel.seconds).where(
                TimeOnTaskModel.started_at >= cutoff
            )
        )
        return [(activity, int(seconds or 0)) for activity, seconds in result.all()]
