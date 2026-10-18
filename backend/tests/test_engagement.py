"""Tests for EngagementService -- streaks, XP, achievements, focus sessions."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import PomodoroSessionModel
from app.repos.engagement_repo import EngagementRepo
from app.services.engagement_service import (
    EngagementService,
    compute_level,
    xp_for_next_level,
)
from app.services.pomodoro_service import PomodoroService

# Fixtures


@pytest.fixture
async def session(test_db):
    _, factory, _ = test_db
    async with factory() as s:
        yield s


@pytest.fixture
async def svc(session):
    return EngagementService(session)


# Level computation


class TestLevelComputation:
    def test_level_zero_below_100(self):
        assert compute_level(0) == 0
        assert compute_level(50) == 0
        assert compute_level(99) == 0

    def test_level_1_at_100(self):
        assert compute_level(100) == 1

    def test_level_5_at_2500(self):
        assert compute_level(2500) == 5

    def test_level_10_at_10000(self):
        assert compute_level(10000) == 10

    def test_xp_for_next_level_at_zero(self):
        assert xp_for_next_level(0) == 100

    def test_xp_for_next_level_at_100(self):
        # Level 1, next level 2 needs 400 XP total
        assert xp_for_next_level(100) == 400


# Streaks


class TestStreaks:
    @pytest.mark.asyncio
    async def test_first_study_starts_streak(self, svc, session):
        streak = await svc.record_study_activity()
        await session.commit()
        assert streak.current_streak == 1
        assert streak.last_study_date == datetime.now(UTC).date()

    @pytest.mark.asyncio
    async def test_same_day_no_double_increment(self, svc, session):
        await svc.record_study_activity()
        await session.commit()
        streak = await svc.record_study_activity()
        await session.commit()
        assert streak.current_streak == 1

    @pytest.mark.asyncio
    async def test_get_streak_returns_dict(self, svc, session):
        await svc.record_study_activity()
        await session.commit()
        result = await svc.get_streak()
        assert result["current_streak"] == 1
        assert result["studied_today"] is True
        assert result["freezes_available"] == 2

    @pytest.mark.asyncio
    async def test_longest_streak_tracked(self, svc, session):
        streak = await svc.record_study_activity()
        await session.commit()
        assert streak.longest_streak == 1


# XP


class TestXP:
    @pytest.mark.asyncio
    async def test_flashcard_xp_easy(self, svc, session):
        xp = await svc.award_flashcard_xp("easy", "card-1")
        await session.commit()
        assert xp == 10  # base 10 * 1.0

    @pytest.mark.asyncio
    async def test_flashcard_xp_hard(self, svc, session):
        xp = await svc.award_flashcard_xp("hard", "card-2")
        await session.commit()
        assert xp == 25  # base 10 * 2.5

    @pytest.mark.asyncio
    async def test_flashcard_xp_good(self, svc, session):
        xp = await svc.award_flashcard_xp("good", "card-3")
        await session.commit()
        assert xp == 15  # base 10 * 1.5

    @pytest.mark.asyncio
    async def test_flashcard_xp_again(self, svc, session):
        xp = await svc.award_flashcard_xp("again", "card-4")
        await session.commit()
        assert xp == 5  # base 10 * 0.5

    @pytest.mark.asyncio
    async def test_note_xp_base(self, svc, session):
        xp = await svc.award_note_xp("note-1", tag_count=0)
        await session.commit()
        assert xp == 15

    @pytest.mark.asyncio
    async def test_note_xp_tag_bonus(self, svc, session):
        xp = await svc.award_note_xp("note-2", tag_count=3)
        await session.commit()
        assert xp == 20  # 15 + 5 bonus

    @pytest.mark.asyncio
    async def test_xp_summary(self, svc, session):
        await svc.award_note_xp("note-1", tag_count=0)
        await svc.award_flashcard_xp("good", "card-1")
        await session.commit()
        summary = await svc.get_xp_summary()
        # 15 (note) + 15 (flashcard good) + streak XP from record_study_activity
        assert summary["total_xp"] >= 30
        assert summary["today_xp"] >= 30
        assert "level" in summary
        assert "xp_to_next_level" in summary

    @pytest.mark.asyncio
    async def test_xp_history(self, svc, session):
        await svc.award_note_xp("note-1", tag_count=0)
        await session.commit()
        history = await svc.get_xp_history(days=7)
        assert len(history) == 7
        # Today should have some XP
        today_entry = history[-1]
        assert today_entry["date"] == str(datetime.now(UTC).date())
        assert today_entry["xp"] > 0


# Achievements


class TestAchievements:
    @pytest.mark.asyncio
    async def test_seed_achievements(self, svc, session):
        await svc.seed_achievements()
        await session.commit()
        achievements = await svc.get_achievements()
        assert len(achievements) > 0
        keys = {a["key"] for a in achievements}
        assert "streak_3" in keys
        assert "cards_1" in keys

    @pytest.mark.asyncio
    async def test_first_card_unlocks(self, svc, session):
        await svc.seed_achievements()
        await svc.award_flashcard_xp("good", "card-1")
        await session.commit()
        achievements = await svc.get_achievements()
        first_card = next(a for a in achievements if a["key"] == "cards_1")
        assert first_card["unlocked_at"] is not None

    @pytest.mark.asyncio
    async def test_recent_achievements(self, svc, session):
        await svc.seed_achievements()
        await svc.award_flashcard_xp("good", "card-1")
        await session.commit()
        recent = await svc.get_recent_achievements(days=7)
        assert len(recent) >= 1


# Focus sessions: the header timer's pomodoros


class TestFocusSessions:
    """The timer the UI drives writes pomodoro_sessions; XP, the focus achievements and
    the Study Habits stats all read it. They once read a second table nothing wrote, so a
    library with 194 completed pomodoros showed zero focus sessions and earned no XP."""

    @pytest.mark.asyncio
    async def test_completing_a_pomodoro_awards_focus_xp(self, svc, session):
        pomodoros = PomodoroService(session)
        row = await pomodoros.start_session(focus_minutes=25)
        await pomodoros.complete_session(row.id)
        assert (await svc.get_xp_summary())["total_xp"] == 20

    @pytest.mark.asyncio
    async def test_an_abandoned_pomodoro_earns_nothing(self, svc, session):
        pomodoros = PomodoroService(session)
        row = await pomodoros.start_session(focus_minutes=25)
        await pomodoros.abandon_session(row.id)
        assert (await svc.get_xp_summary())["total_xp"] == 0

    @pytest.mark.asyncio
    async def test_focus_stats_count_pomodoros(self, svc, session):
        pomodoros = PomodoroService(session)
        done = await pomodoros.start_session(focus_minutes=25)
        await pomodoros.complete_session(done.id)
        dropped = await pomodoros.start_session(focus_minutes=25)
        await pomodoros.abandon_session(dropped.id)

        stats = await svc.get_focus_stats(days=7)
        assert stats["total_sessions"] == 2
        assert stats["completed_sessions"] == 1
        assert stats["completion_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_focus_minutes_leave_out_paused_time(self, svc, session):
        start = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        session.add(
            PomodoroSessionModel(
                id="p1",
                started_at=start,
                completed_at=start + timedelta(minutes=30),
                pause_accumulated_seconds=5 * 60,
                status="completed",
                created_at=start,
            )
        )
        await session.commit()
        stats = await EngagementService(session).get_focus_stats(days=36500)
        assert stats["total_focus_minutes"] == 25.0

    @pytest.mark.asyncio
    async def test_focus_achievements_unlock_from_pomodoros(self, svc, session):
        await svc.seed_achievements()
        pomodoros = PomodoroService(session)
        row = await pomodoros.start_session(focus_minutes=50)
        await pomodoros.complete_session(row.id)
        unlocked = {a["key"] for a in await svc.get_achievements() if a["unlocked_at"]}
        assert "focus_50min" in unlocked


# Local-day buckets


@pytest.mark.parametrize(
    ("tz_offset_minutes", "expected_day"),
    [
        (0, "2026-10-18"),  # UTC: 03:00 is the same day
        (420, "2026-10-17"),  # PDT: 03:00 UTC is 20:00 the evening before
        (-330, "2026-10-18"),  # IST: 08:30 the same morning
    ],
)
async def test_xp_buckets_on_the_users_local_day(session, tz_offset_minutes, expected_day):
    repo = EngagementRepo(session, tz_offset_minutes)
    entry = await repo.add_xp("flashcard_review", 10, None)
    entry.created_at = datetime(2026, 10, 18, 3, 0)
    await session.flush()

    assert await repo.xp_by_day_since("2026-10-01") == {expected_day: 10}
