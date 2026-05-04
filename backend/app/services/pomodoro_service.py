"""S208: Pomodoro session service.

State machine: active <-> paused -> completed | abandoned.
At most one row may exist with status in (active, paused) at any time.

Stats:
- today_count: completed sessions whose created_at falls within today's UTC date.
- streak_days: consecutive UTC dates ending today with at least one completion.
- total_completed: lifetime completed count.

Goalless sessions (goal_id NULL) still count toward stats; the goal_id column is a
free-form string in this story and gets a real FK in S210.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PomodoroSessionModel

logger = logging.getLogger(__name__)

VALID_SURFACES = {"read", "recall", "write", "explore", "none"}
ACTIVE_STATUSES = ("active", "paused")


class PomodoroError(Exception):
    """Base for service-level pomodoro errors."""


class ActiveSessionExists(PomodoroError):
    """Raised by start_session when an active or paused session already exists."""

    def __init__(self, existing_id: str) -> None:
        super().__init__(f"active or paused session already exists: {existing_id}")
        self.existing_id = existing_id


class SessionNotFound(PomodoroError):
    """Raised when the requested session id is not in the database."""


class InvalidTransition(PomodoroError):
    """Raised when a transition is invalid for the current status."""

    def __init__(self, session_id: str, from_status: str, action: str) -> None:
        super().__init__(
            f"cannot {action} session {session_id} from status={from_status}"
        )
        self.session_id = session_id
        self.from_status = from_status
        self.action = action


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(dt: datetime) -> datetime:
    """SQLite returns tz-naive datetimes; treat them as UTC for arithmetic."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class PomodoroService:
    """Owns Pomodoro state transitions and stat aggregation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ helpers

    async def _get(self, session_id: str) -> PomodoroSessionModel:
        result = await self._session.execute(
            select(PomodoroSessionModel).where(PomodoroSessionModel.id == session_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise SessionNotFound(f"pomodoro session {session_id} not found")
        return row

    async def _get_active_or_paused(self) -> PomodoroSessionModel | None:
        result = await self._session.execute(
            select(PomodoroSessionModel).where(
                PomodoroSessionModel.status.in_(ACTIVE_STATUSES)
            )
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------ commands

    async def start_session(
        self,
        focus_minutes: int = 25,
        break_minutes: int = 5,
        surface: str = "none",
        document_id: str | None = None,
        deck_id: str | None = None,
        goal_id: str | None = None,
    ) -> PomodoroSessionModel:
        if surface not in VALID_SURFACES:
            raise ValueError(f"invalid surface: {surface}")
        if focus_minutes < 1 or break_minutes < 1:
            raise ValueError("focus_minutes and break_minutes must be >= 1")

        existing = await self._get_active_or_paused()
        if existing is not None:
            raise ActiveSessionExists(existing.id)

        now = _now()
        row = PomodoroSessionModel(
            id=str(uuid.uuid4()),
            started_at=now,
            focus_minutes=focus_minutes,
            break_minutes=break_minutes,
            status="active",
            surface=surface,
            document_id=document_id,
            deck_id=deck_id,
            goal_id=goal_id,
            pause_accumulated_seconds=0,
            created_at=now,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        logger.info("Started pomodoro %s surface=%s", row.id, surface)
        return row

    async def pause_session(self, session_id: str) -> PomodoroSessionModel:
        row = await self._get(session_id)
        if row.status != "active":
            raise InvalidTransition(session_id, row.status, "pause")
        row.status = "paused"
        row.paused_at = _now()
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def resume_session(self, session_id: str) -> PomodoroSessionModel:
        row = await self._get(session_id)
        if row.status != "paused":
            raise InvalidTransition(session_id, row.status, "resume")
        if row.paused_at is not None:
            elapsed = (_now() - _as_utc(row.paused_at)).total_seconds()
            if elapsed > 0:
                row.pause_accumulated_seconds += int(elapsed)
        row.paused_at = None
        row.status = "active"
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def complete_session(self, session_id: str) -> PomodoroSessionModel:
        row = await self._get(session_id)
        if row.status not in ACTIVE_STATUSES:
            raise InvalidTransition(session_id, row.status, "complete")
        # Roll any pending pause into the accumulator before completing.
        if row.status == "paused" and row.paused_at is not None:
            elapsed = (_now() - _as_utc(row.paused_at)).total_seconds()
            if elapsed > 0:
                row.pause_accumulated_seconds += int(elapsed)
            row.paused_at = None
        row.status = "completed"
        row.completed_at = _now()
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def abandon_session(self, session_id: str) -> PomodoroSessionModel:
        row = await self._get(session_id)
        if row.status not in ACTIVE_STATUSES:
            raise InvalidTransition(session_id, row.status, "abandon")
        row.status = "abandoned"
        await self._session.commit()
        await self._session.refresh(row)
        return row

    # ------------------------------------------------------------------ queries

    async def get_active_session(self) -> PomodoroSessionModel | None:
        return await self._get_active_or_paused()

    async def get_session(self, session_id: str) -> PomodoroSessionModel | None:
        result = await self._session.execute(
            select(PomodoroSessionModel).where(PomodoroSessionModel.id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_stats(self) -> dict:
        today = _now().date()
        midnight_today = datetime.combine(today, datetime.min.time(), tzinfo=UTC)

        today_count = (
            await self._session.execute(
                select(func.count(PomodoroSessionModel.id)).where(
                    PomodoroSessionModel.status == "completed",
                    PomodoroSessionModel.created_at >= midnight_today,
                )
            )
        ).scalar_one()

        total_completed = (
            await self._session.execute(
                select(func.count(PomodoroSessionModel.id)).where(
                    PomodoroSessionModel.status == "completed"
                )
            )
        ).scalar_one()

        # Pull every completed created_at; in practice the volume is small (one user, local).
        rows = (
            await self._session.execute(
                select(PomodoroSessionModel.created_at).where(
                    PomodoroSessionModel.status == "completed"
                )
            )
        ).all()
        completed_dates: set[date] = set()
        for (created_at,) in rows:
            if created_at is None:
                continue
            ts = (
                created_at
                if created_at.tzinfo is not None
                else created_at.replace(tzinfo=UTC)
            )
            completed_dates.add(ts.date())

        streak = 0
        cursor = today
        while cursor in completed_dates:
            streak += 1
            cursor = cursor - timedelta(days=1)

        return {
            "today_count": int(today_count),
            "streak_days": streak,
            "total_completed": int(total_completed),
        }


def get_pomodoro_service(session: AsyncSession) -> PomodoroService:
    return PomodoroService(session)
