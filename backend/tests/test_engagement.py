"""Tests for EngagementService -- streaks, XP, achievements, focus sessions."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.services.engagement_service import (
    EngagementService,
    compute_level,
    xp_for_next_level,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


@pytest.fixture
async def session(test_db):
    _, factory, _ = test_db
    async with factory() as s:
        yield s


@pytest.fixture
async def svc(session):
    return EngagementService(session)


# ---------------------------------------------------------------------------
# Level computation
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Streaks
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# XP
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Achievements
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Focus Sessions
# ---------------------------------------------------------------------------


class TestFocusSessions:
    @pytest.mark.asyncio
    async def test_start_session(self, svc, session):
        fs = await svc.start_focus_session(25, "study")
        assert fs.id is not None
        assert fs.planned_duration_minutes == 25
        assert fs.completed is False

    @pytest.mark.asyncio
    async def test_complete_session(self, svc, session):
        fs = await svc.start_focus_session(25, "study")
        result = await svc.complete_focus_session(fs.id)
        assert result["xp_awarded"] == 20
        assert result["already_completed"] is False

    @pytest.mark.asyncio
    async def test_complete_idempotent(self, svc, session):
        fs = await svc.start_focus_session(25, "study")
        await svc.complete_focus_session(fs.id)
        result = await svc.complete_focus_session(fs.id)
        assert result["already_completed"] is True

    @pytest.mark.asyncio
    async def test_cancel_session(self, svc, session):
        fs = await svc.start_focus_session(25, "study")
        result = await svc.cancel_focus_session(fs.id)
        assert result["cancelled"] is True

    @pytest.mark.asyncio
    async def test_cancel_no_xp(self, svc, session):
        fs = await svc.start_focus_session(25, "study")
        await svc.cancel_focus_session(fs.id)
        summary = await svc.get_xp_summary()
        # Should be 0 XP -- cancelled sessions don't award XP
        assert summary["total_xp"] == 0

    @pytest.mark.asyncio
    async def test_today_sessions(self, svc, session):
        await svc.start_focus_session(25, "study")
        await svc.start_focus_session(15, "notes")
        sessions = await svc.get_today_sessions()
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_focus_stats(self, svc, session):
        fs = await svc.start_focus_session(25, "study")
        await svc.complete_focus_session(fs.id)
        stats = await svc.get_focus_stats(days=7)
        assert stats["total_sessions"] == 1
        assert stats["completed_sessions"] == 1
        assert stats["completion_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_not_found_raises(self, svc):
        with pytest.raises(ValueError, match="not found"):
            await svc.complete_focus_session("nonexistent")
