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

import logging
import math
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AchievementModel,
    PomodoroSessionModel,
    StudyStreakModel,
    XPLedgerModel,
)
from app.repos.engagement_repo import EngagementRepo

logger = logging.getLogger(__name__)

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
    return math.floor(math.sqrt(total_xp / 100))


def xp_for_next_level(total_xp: int) -> int:
    """XP required to reach the next level."""
    current_level = compute_level(total_xp)
    next_level = current_level + 1
    return (next_level * next_level) * 100


def _focused_seconds(row: PomodoroSessionModel) -> float:
    """Wall time from start to completion, less the time spent paused."""
    started, completed = (_as_utc(row.started_at), _as_utc(row.completed_at))
    return max(0.0, (completed - started).total_seconds() - row.pause_accumulated_seconds)


def _as_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; attach UTC if missing."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class EngagementService:
    """Manages streaks, XP, achievements, and focus-session stats.

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
        self._repo = EngagementRepo(session, tz_offset_minutes)

    def _local_today(self) -> date:
        """Return the user's current local date, derived from UTC + offset."""
        return (datetime.now(UTC) - timedelta(minutes=self._tz_offset_minutes)).date()

    # ------------------------------------------------------------------
    # Streak
    # ------------------------------------------------------------------

    async def record_study_activity(self) -> StudyStreakModel:
        """Call on any qualifying study action. Updates streak and awards streak bonus XP."""
        streak = await self._repo.streak()
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
        streak = await self._repo.streak()
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
        return await self._repo.add_xp(action, amount, detail)

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
        """Award XP for creating a note. Bonus for 2+ tags.

        `tag_count` is whatever the caller supplied explicitly. A note saved
        with none is tagged in the background (`auto_tag_and_store_note`),
        which awards the same bonus itself via `award_note_tag_bonus` once
        tags actually land, so this never blocks on the tagger's LLM call.
        """
        xp = _NOTE_XP
        if tag_count >= 2:
            xp += _NOTE_TAG_BONUS
        await self._add_xp("note_created", xp, {"note_id": note_id, "tags": tag_count})
        await self._check_achievements()
        await self._session.flush()
        return xp

    async def award_note_tag_bonus(self, note_id: str, tag_count: int) -> int:
        """Award the 2+ tags bonus for a note auto-tagged after creation."""
        if tag_count < 2:
            return 0
        await self._add_xp("note_tagged", _NOTE_TAG_BONUS, {"note_id": note_id, "tags": tag_count})
        await self._check_achievements()
        await self._session.flush()
        return _NOTE_TAG_BONUS

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
        total_xp = await self._repo.total_xp()
        today_xp = await self._repo.xp_on(str(self._local_today()))

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
        history = await self._repo.xp_by_day_since(str(today_local - timedelta(days=days - 1)))

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
        existing = await self._repo.achievement_keys()
        for key, title, description, icon, category, target in ACHIEVEMENT_DEFS:
            if key not in existing:
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
        for ach in await self._repo.locked_achievements():
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
            return (await self._repo.streak()).longest_streak
        if key.startswith("cards_"):
            return await self._repo.count_xp_actions("flashcard_review")
        if key.startswith("notes_"):
            return await self._repo.count_xp_actions("note_created")
        if key == "focus_10":
            return await self._repo.count_completed_pomodoros()
        if key == "focus_50min":
            return await self._repo.count_completed_pomodoros(min_focus_minutes=50)
        if key.startswith("xp_"):
            return await self._repo.total_xp()

        return 0

    async def get_achievements(self) -> list[dict]:
        """Return all achievements with unlock status and progress."""
        await self.seed_achievements()
        achievements = []
        for ach in await self._repo.all_achievements():
            progress = await self._get_achievement_progress(ach.key)
            achievements.append(
                {
                    "key": ach.key,
                    "title": ach.title,
                    "description": ach.description,
                    "icon_name": ach.icon_name,
                    "category": ach.category,
                    "progress_current": progress,
                    "progress_target": ach.progress_target,
                    "unlocked_at": ach.unlocked_at.isoformat() if ach.unlocked_at else None,
                }
            )
        return achievements

    async def get_recent_achievements(self, days: int = 7) -> list[dict]:
        """Return achievements unlocked in the last N days."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        return [
            {
                "key": ach.key,
                "title": ach.title,
                "description": ach.description,
                "icon_name": ach.icon_name,
                "category": ach.category,
                "unlocked_at": ach.unlocked_at.isoformat() if ach.unlocked_at else None,
            }
            for ach in await self._repo.achievements_unlocked_since(cutoff)
        ]

    # ------------------------------------------------------------------
    # Focus Sessions
    # ------------------------------------------------------------------

    async def get_focus_stats(self, days: int = 7) -> dict:
        start_str = str(self._local_today() - timedelta(days=days - 1))
        sessions = await self._repo.pomodoros_since(start_str)
        done = [s for s in sessions if s.status == "completed" and s.completed_at is not None]
        total = len(sessions)
        completed = len(done)
        total_minutes = sum(_focused_seconds(s) for s in done) / 60
        avg_duration = total_minutes / completed if completed > 0 else 0

        return {
            "total_sessions": total,
            "completed_sessions": completed,
            "completion_rate": round(completed / total, 2) if total > 0 else 0,
            "total_focus_minutes": round(total_minutes, 1),
            "avg_duration_minutes": round(avg_duration, 1),
            "days": days,
        }
