"""Streak, XP ledger, achievements and focus sessions."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AchievementModel,
    FocusSessionModel,
    StudyStreakModel,
    XPLedgerModel,
)
from app.repos._helpers import local_date

# Singleton streak row ID (local-first, single user)
_STREAK_ID = "local"


class EngagementRepo:
    """Day buckets are the user's local dates, per `tz_offset_minutes` (see `local_date`)."""

    def __init__(self, session: AsyncSession, tz_offset_minutes: int = 0) -> None:
        self.session = session
        self._tz_offset_minutes = tz_offset_minutes

    def _day(self, column):
        return local_date(column, self._tz_offset_minutes)

    async def _scalar(self, stmt) -> int:
        return (await self.session.execute(stmt)).scalar() or 0

    # -- streak ------------------------------------------------------------

    async def streak(self) -> StudyStreakModel:
        row = await self.session.get(StudyStreakModel, _STREAK_ID)
        if row is None:
            row = StudyStreakModel(id=_STREAK_ID, current_streak=0, longest_streak=0)
            self.session.add(row)
            await self.session.flush()
        return row

    # -- XP ledger ---------------------------------------------------------

    async def add_xp(self, action: str, amount: int, detail: dict | None) -> XPLedgerModel:
        entry = XPLedgerModel(
            id=str(uuid.uuid4()),
            action=action,
            xp_amount=amount,
            detail_json=json.dumps(detail) if detail else None,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def total_xp(self) -> int:
        return await self._scalar(select(func.coalesce(func.sum(XPLedgerModel.xp_amount), 0)))

    async def xp_on(self, day: str) -> int:
        return await self._scalar(
            select(func.coalesce(func.sum(XPLedgerModel.xp_amount), 0)).where(
                self._day(XPLedgerModel.created_at) == day
            )
        )

    async def xp_by_day_since(self, start_day: str) -> dict[str, int]:
        day = self._day(XPLedgerModel.created_at)
        rows = await self.session.execute(
            select(day.label("day"), func.sum(XPLedgerModel.xp_amount).label("xp"))
            .where(day >= start_day)
            .group_by(day)
            .order_by(day)
        )
        return {str(row.day): row.xp for row in rows}

    async def count_xp_actions(self, action: str) -> int:
        return await self._scalar(
            select(func.count()).select_from(XPLedgerModel).where(XPLedgerModel.action == action)
        )

    # -- achievements ------------------------------------------------------

    async def achievement_keys(self) -> set[str]:
        return set((await self.session.execute(select(AchievementModel.key))).scalars().all())

    async def locked_achievements(self) -> list[AchievementModel]:
        result = await self.session.execute(
            select(AchievementModel).where(AchievementModel.unlocked_at.is_(None))
        )
        return list(result.scalars().all())

    async def all_achievements(self) -> list[AchievementModel]:
        result = await self.session.execute(
            select(AchievementModel).order_by(AchievementModel.category, AchievementModel.key)
        )
        return list(result.scalars().all())

    async def achievements_unlocked_since(self, cutoff: datetime) -> list[AchievementModel]:
        result = await self.session.execute(
            select(AchievementModel)
            .where(AchievementModel.unlocked_at.is_not(None))
            .where(AchievementModel.unlocked_at >= cutoff)
            .order_by(AchievementModel.unlocked_at.desc())
        )
        return list(result.scalars().all())

    # -- focus sessions ----------------------------------------------------

    async def count_completed_focus_sessions(self, min_planned_minutes: int = 0) -> int:
        return await self._scalar(
            select(func.count())
            .select_from(FocusSessionModel)
            .where(
                FocusSessionModel.completed.is_(True),
                FocusSessionModel.planned_duration_minutes >= min_planned_minutes,
            )
        )

    async def focus_sessions_on(self, day: str) -> list[FocusSessionModel]:
        result = await self.session.execute(
            select(FocusSessionModel)
            .where(self._day(FocusSessionModel.started_at) == day)
            .order_by(FocusSessionModel.started_at.desc())
        )
        return list(result.scalars().all())

    async def focus_sessions_since(self, start_day: str) -> list[FocusSessionModel]:
        result = await self.session.execute(
            select(FocusSessionModel).where(self._day(FocusSessionModel.started_at) >= start_day)
        )
        return list(result.scalars().all())
