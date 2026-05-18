"""EngagementService -- streaks, XP, achievements, focus sessions.

XP weighting philosophy: reward learning quality, not speed.
- Flashcard review: base 10 XP, scaled by FSRS difficulty
  (easy=1x, good=1.5x, hard=2.5x, again=0.5x)
- Note created: 15 XP (+5 bonus if 2+ tags)
- Focus session completed: 20 XP
- Streak bonus: current_streak * 5 XP (once daily on first study action)

Level formula: level = floor(sqrt(total_xp / 100))
  Level 1 = 100 XP, Level 5 = 2500 XP, Level 10 = 10000 XP
"""

import json
import logging
import math
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AchievementModel,
    FocusSessionModel,
    StudyStreakModel,
    XPLedgerModel,
)

logger = logging.getLogger(__name__)

# Singleton streak row ID (local-first, single user)
_STREAK_ID = "local"

# XP multipliers by FSRS rating
_RATING_MULTIPLIERS: dict[str, float] = {
    "easy": 1.0,
    "good": 1.5,
    "hard": 2.5,
    "again": 0.5,
}

_BASE_FLASHCARD_XP = 10
_NOTE_XP = 15
_NOTE_TAG_BONUS = 5
_FOCUS_SESSION_XP = 20
_SECTION_READ_XP = 5
_MAX_READING_XP_PER_DOC_PER_DAY = 50

# Achievement definitions: (key, title, description, icon, category, target)
ACHIEVEMENT_DEFS: list[tuple[str, str, str, str, str, int]] = [
    # Streak
    ("streak_3", "First Flame", "Maintain a 3-day study streak", "flame", "streak", 3),
    ("streak_7", "Week Warrior", "Maintain a 7-day study streak", "flame", "streak", 7),
    ("streak_30", "Monthly Master", "Maintain a 30-day study streak", "flame", "streak", 30),
    ("streak_100", "Century Club", "Maintain a 100-day study streak", "flame", "streak", 100),
    # Mastery
    ("cards_1", "First Card", "Review your first flashcard", "zap", "mastery", 1),
    ("cards_100", "Card Centurion", "Review 100 flashcards", "zap", "mastery", 100),
    ("cards_1000", "Card Thousand", "Review 1000 flashcards", "zap", "mastery", 1000),
    # Exploration
    ("notes_10", "Note Taker", "Create 10 notes", "sticky-note", "exploration", 10),
    ("notes_50", "Knowledge Weaver", "Create 50 notes", "sticky-note", "exploration", 50),
    # Consistency
    ("focus_10", "Focus Master", "Complete 10 focus sessions", "timer", "consistency", 10),
    ("focus_50min", "Deep Work", "Complete a 50-minute focus session", "timer", "consistency", 1),
    ("xp_1000", "XP Milestone", "Earn 1000 total XP", "trophy", "consistency", 1000),
    ("xp_5000", "XP Legend", "Earn 5000 total XP", "trophy", "consistency", 5000),
]


def compute_level(total_xp: int) -> int:
    """Level = floor(sqrt(total_xp / 100)). Level 0 until 100 XP."""
    if total_xp < 100:
        return 0
    return int(math.floor(math.sqrt(total_xp / 100)))


def xp_for_next_level(total_xp: int) -> int:
    """XP required to reach the next level."""
    current_level = compute_level(total_xp)
    next_level = current_level + 1
    return (next_level * next_level) * 100


class EngagementService:
    """Manages streaks, XP, achievements, and focus sessions.

    `tz_offset_minutes` matches JS `Date.getTimezoneOffset()` (positive
    west of UTC; PDT=420). It controls how "today" is computed for
    streaks, XP-today, and the daily XP/focus chart buckets so that a
    study session at 11pm local time doesn't roll over into "tomorrow".
    Defaults to 0 (UTC) for callers that don't propagate the offset --
    legacy behavior, slightly wrong near UTC midnight but not data-loss.
    """

    def __init__(self, session: AsyncSession, tz_offset_minutes: int = 0) -> None:
        self._session = session
        self._tz_offset_minutes = tz_offset_minutes

    def _local_today(self) -> date:
        """Return the user's current local date, derived from UTC + offset."""
        return (datetime.now(UTC) - timedelta(minutes=self._tz_offset_minutes)).date()

    def _local_date_sql(self, column):
        """SQL expression: cast a UTC datetime column to the user's local date.

        SQLite's `datetime(x, '<N> minutes')` modifier handles the shift; the
        outer `date(...)` strips the time component. With tz_offset_minutes=0
        this is equivalent to the prior `func.date(column)` behavior.
        """
        if self._tz_offset_minutes == 0:
            return func.date(column)
        modifier = f"{-self._tz_offset_minutes:+d} minutes"
        return func.date(func.datetime(column, modifier))

    # ------------------------------------------------------------------
    # Streak
    # ------------------------------------------------------------------

    async def _get_or_create_streak(self) -> StudyStreakModel:
        result = await self._session.get(StudyStreakModel, _STREAK_ID)
        if result is None:
            result = StudyStreakModel(id=_STREAK_ID, current_streak=0, longest_streak=0)
            self._session.add(result)
            await self._session.flush()
        return result

    async def record_study_activity(self) -> StudyStreakModel:
        """Call on any qualifying study action. Updates streak and awards streak bonus XP."""
        streak = await self._get_or_create_streak()
        today = self._local_today()

        # Reset weekly freezes on Monday
        is_monday = today.weekday() == 0
        needs_reset = streak.week_start_date is None or streak.week_start_date < today
        if streak.week_start_date is None or (is_monday and needs_reset):
            streak.streak_freezes_available = 2
            streak.streak_freezes_used_this_week = 0
            streak.week_start_date = today

        if streak.last_study_date == today:
            # Already studied today -- no streak change
            return streak

        if streak.last_study_date is not None:
            gap = (today - streak.last_study_date).days
        else:
            gap = 0  # First ever study

        if gap <= 1:
            # Consecutive day or first day
            streak.current_streak += 1
        elif gap <= 1 + streak.streak_freezes_available:
            # Can cover the gap with freezes
            freezes_needed = gap - 1
            streak.streak_freezes_available -= freezes_needed
            streak.streak_freezes_used_this_week += freezes_needed
            streak.current_streak += 1
        else:
            # Streak broken
            streak.current_streak = 1

        streak.last_study_date = today
        streak.longest_streak = max(streak.longest_streak, streak.current_streak)
        streak.updated_at = datetime.now(UTC)

        # Award streak bonus XP (once daily)
        if streak.current_streak > 1:
            bonus = streak.current_streak * 5
            await self._add_xp("streak_bonus", bonus, {"streak": streak.current_streak})

        await self._session.flush()
        return streak

    async def get_streak(self) -> dict:
        streak = await self._get_or_create_streak()
        today = self._local_today()
        studied_today = streak.last_study_date == today
        return {
            "current_streak": streak.current_streak,
            "longest_streak": streak.longest_streak,
            "studied_today": studied_today,
            "freezes_available": streak.streak_freezes_available,
            "last_study_date": str(streak.last_study_date) if streak.last_study_date else None,
        }

    # ------------------------------------------------------------------
    # XP
    # ------------------------------------------------------------------

    async def _add_xp(self, action: str, amount: int, detail: dict | None = None) -> XPLedgerModel:
        entry = XPLedgerModel(
            id=str(uuid.uuid4()),
            action=action,
            xp_amount=amount,
            detail_json=json.dumps(detail) if detail else None,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def award_flashcard_xp(self, rating: str, card_id: str) -> int:
        """Award XP for a flashcard review. Returns XP amount."""
        multiplier = _RATING_MULTIPLIERS.get(rating, 1.0)
        xp = int(_BASE_FLASHCARD_XP * multiplier)
        await self._add_xp("flashcard_review", xp, {"rating": rating, "card_id": card_id})
        await self.record_study_activity()
        await self._check_achievements()
        await self._session.flush()
        return xp

    async def award_note_xp(self, note_id: str, tag_count: int) -> int:
        """Award XP for creating a note. Bonus for 2+ tags."""
        xp = _NOTE_XP
        if tag_count >= 2:
            xp += _NOTE_TAG_BONUS
        await self._add_xp("note_created", xp, {"note_id": note_id, "tags": tag_count})
        await self._check_achievements()
        await self._session.flush()
        return xp

    async def award_focus_session_xp(self, session_id: str) -> int:
        """Award XP for completing a focus session."""
        xp = _FOCUS_SESSION_XP
        await self._add_xp("focus_session_completed", xp, {"session_id": session_id})
        await self.record_study_activity()
        await self._check_achievements()
        await self._session.flush()
        return xp

    async def get_xp_summary(self) -> dict:
        """Return total XP, level, XP to next level, today's XP."""
        total_result = await self._session.execute(
            select(func.coalesce(func.sum(XPLedgerModel.xp_amount), 0))
        )
        total_xp = total_result.scalar() or 0

        today_str = str(self._local_today())
        local_date = self._local_date_sql(XPLedgerModel.created_at)
        today_result = await self._session.execute(
            select(func.coalesce(func.sum(XPLedgerModel.xp_amount), 0)).where(
                local_date == today_str
            )
        )
        today_xp = today_result.scalar() or 0

        level = compute_level(total_xp)
        next_level_xp = xp_for_next_level(total_xp)

        return {
            "total_xp": total_xp,
            "level": level,
            "xp_to_next_level": next_level_xp - total_xp,
            "today_xp": today_xp,
        }

    async def get_xp_history(self, days: int = 30) -> list[dict]:
        """Return daily XP totals for the last N days, bucketed in local time."""
        today_local = self._local_today()
        start_str = str(today_local - timedelta(days=days - 1))
        local_date = self._local_date_sql(XPLedgerModel.created_at)
        rows = await self._session.execute(
            select(
                local_date.label("day"),
                func.sum(XPLedgerModel.xp_amount).label("xp"),
            )
            .where(local_date >= start_str)
            .group_by(local_date)
            .order_by(local_date)
        )
        history = {str(row.day): row.xp for row in rows}

        # Fill in zero-days
        result = []
        for i in range(days):
            d = today_local - timedelta(days=days - 1 - i)
            result.append({"date": str(d), "xp": history.get(str(d), 0)})
        return result

    # ------------------------------------------------------------------
    # Achievements
    # ------------------------------------------------------------------

    async def seed_achievements(self) -> None:
        """Ensure all achievement definitions exist in the DB. Idempotent."""
        for key, title, description, icon, category, target in ACHIEVEMENT_DEFS:
            existing = await self._session.execute(
                select(AchievementModel).where(AchievementModel.key == key)
            )
            if existing.scalar_one_or_none() is None:
                self._session.add(
                    AchievementModel(
                        id=str(uuid.uuid4()),
                        key=key,
                        title=title,
                        description=description,
                        icon_name=icon,
                        category=category,
                        progress_target=target,
                    )
                )
        await self._session.flush()

    async def _check_achievements(self) -> list[AchievementModel]:
        """Check all locked achievements and unlock any that have been earned."""
        unlocked = []
        locked = await self._session.execute(
            select(AchievementModel).where(AchievementModel.unlocked_at.is_(None))
        )
        for ach in locked.scalars().all():
            progress = await self._get_achievement_progress(ach.key)
            ach.progress_current = progress
            if progress >= ach.progress_target:
                ach.unlocked_at = datetime.now(UTC)
                unlocked.append(ach)
                logger.info("Achievement unlocked: %s", ach.key)
        if unlocked:
            await self._session.flush()
        return unlocked

    async def _get_achievement_progress(self, key: str) -> int:
        """Compute current progress for a given achievement key."""
        if key.startswith("streak_"):
            streak = await self._get_or_create_streak()
            return streak.longest_streak

        if key.startswith("cards_"):
            result = await self._session.execute(
                select(func.count()).select_from(XPLedgerModel).where(
                    XPLedgerModel.action == "flashcard_review"
                )
            )
            return result.scalar() or 0

        if key.startswith("notes_"):
            result = await self._session.execute(
                select(func.count()).select_from(XPLedgerModel).where(
                    XPLedgerModel.action == "note_created"
                )
            )
            return result.scalar() or 0

        if key == "focus_10":
            result = await self._session.execute(
                select(func.count()).select_from(FocusSessionModel).where(
                    FocusSessionModel.completed.is_(True)
                )
            )
            return result.scalar() or 0

        if key == "focus_50min":
            result = await self._session.execute(
                select(func.count()).select_from(FocusSessionModel).where(
                    FocusSessionModel.completed.is_(True),
                    FocusSessionModel.planned_duration_minutes >= 50,
                )
            )
            return result.scalar() or 0

        if key.startswith("xp_"):
            result = await self._session.execute(
                select(func.coalesce(func.sum(XPLedgerModel.xp_amount), 0))
            )
            return result.scalar() or 0

        return 0

    async def get_achievements(self) -> list[dict]:
        """Return all achievements with unlock status and progress."""
        await self.seed_achievements()
        result = await self._session.execute(
            select(AchievementModel).order_by(AchievementModel.category, AchievementModel.key)
        )
        achievements = []
        for ach in result.scalars().all():
            progress = await self._get_achievement_progress(ach.key)
            achievements.append({
                "key": ach.key,
                "title": ach.title,
                "description": ach.description,
                "icon_name": ach.icon_name,
                "category": ach.category,
                "progress_current": progress,
                "progress_target": ach.progress_target,
                "unlocked_at": ach.unlocked_at.isoformat() if ach.unlocked_at else None,
            })
        return achievements

    async def get_recent_achievements(self, days: int = 7) -> list[dict]:
        """Return achievements unlocked in the last N days."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        result = await self._session.execute(
            select(AchievementModel)
            .where(AchievementModel.unlocked_at.is_not(None))
            .where(AchievementModel.unlocked_at >= cutoff)
            .order_by(AchievementModel.unlocked_at.desc())
        )
        return [
            {
                "key": ach.key,
                "title": ach.title,
                "description": ach.description,
                "icon_name": ach.icon_name,
                "category": ach.category,
                "unlocked_at": ach.unlocked_at.isoformat() if ach.unlocked_at else None,
            }
            for ach in result.scalars().all()
        ]

    # ------------------------------------------------------------------
    # Focus Sessions
    # ------------------------------------------------------------------

    async def start_focus_session(
        self, duration_minutes: int, session_type: str = "study"
    ) -> FocusSessionModel:
        session = FocusSessionModel(
            id=str(uuid.uuid4()),
            planned_duration_minutes=duration_minutes,
            session_type=session_type,
        )
        self._session.add(session)
        await self._session.commit()
        await self._session.refresh(session)
        return session

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        """SQLite returns naive datetimes; attach UTC if missing."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt

    async def complete_focus_session(self, session_id: str) -> dict:
        session = await self._session.get(FocusSessionModel, session_id)
        if session is None:
            raise ValueError(f"Focus session {session_id} not found")
        if session.completed:
            return {
                "session_id": session_id,
                "xp_awarded": session.xp_awarded,
                "already_completed": True,
            }

        now = datetime.now(UTC)
        session.ended_at = now
        started = self._ensure_utc(session.started_at)
        session.actual_duration_seconds = int((now - started).total_seconds())
        session.completed = True

        xp = await self.award_focus_session_xp(session_id)
        session.xp_awarded = xp
        await self._session.commit()

        return {"session_id": session_id, "xp_awarded": xp, "already_completed": False}

    async def cancel_focus_session(self, session_id: str) -> dict:
        session = await self._session.get(FocusSessionModel, session_id)
        if session is None:
            raise ValueError(f"Focus session {session_id} not found")

        now = datetime.now(UTC)
        session.ended_at = now
        started = self._ensure_utc(session.started_at)
        session.actual_duration_seconds = int((now - started).total_seconds())
        session.completed = False
        await self._session.commit()

        return {"session_id": session_id, "cancelled": True}

    async def get_today_sessions(self) -> list[dict]:
        today_str = str(self._local_today())
        local_date = self._local_date_sql(FocusSessionModel.started_at)
        result = await self._session.execute(
            select(FocusSessionModel)
            .where(local_date == today_str)
            .order_by(FocusSessionModel.started_at.desc())
        )
        return [
            {
                "id": s.id,
                "started_at": s.started_at.isoformat(),
                "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                "planned_duration_minutes": s.planned_duration_minutes,
                "actual_duration_seconds": s.actual_duration_seconds,
                "session_type": s.session_type,
                "completed": s.completed,
                "xp_awarded": s.xp_awarded,
            }
            for s in result.scalars().all()
        ]

    async def get_focus_stats(self, days: int = 7) -> dict:
        start_str = str(self._local_today() - timedelta(days=days - 1))
        local_date = self._local_date_sql(FocusSessionModel.started_at)
        result = await self._session.execute(
            select(FocusSessionModel).where(local_date >= start_str)
        )
        sessions = result.scalars().all()
        total = len(sessions)
        completed = sum(1 for s in sessions if s.completed)
        total_minutes = sum(
            (s.actual_duration_seconds or 0) / 60 for s in sessions if s.completed
        )
        avg_duration = total_minutes / completed if completed > 0 else 0

        return {
            "total_sessions": total,
            "completed_sessions": completed,
            "completion_rate": round(completed / total, 2) if total > 0 else 0,
            "total_focus_minutes": round(total_minutes, 1),
            "avg_duration_minutes": round(avg_duration, 1),
            "days": days,
        }
