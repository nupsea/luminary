"""Unit tests for PomodoroService (S208)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import PomodoroSessionModel
from app.services.pomodoro_service import (
    ActiveSessionExists,
    InvalidTransition,
    PomodoroService,
    SessionNotFound,
)


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

    yield engine, factory

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Start / 409 invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_session_defaults(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = PomodoroService(db)
        row = await svc.start_session()
    assert row.status == "active"
    assert row.focus_minutes == 25
    assert row.break_minutes == 5
    assert row.surface == "none"
    assert row.goal_id is None
    assert row.pause_accumulated_seconds == 0


@pytest.mark.asyncio
async def test_start_blocked_by_active_session(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = PomodoroService(db)
        first = await svc.start_session()
    async with factory() as db:
        svc = PomodoroService(db)
        with pytest.raises(ActiveSessionExists) as ei:
            await svc.start_session()
        assert ei.value.existing_id == first.id


@pytest.mark.asyncio
async def test_start_blocked_by_paused_session(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = PomodoroService(db)
        first = await svc.start_session()
        await svc.pause_session(first.id)
    async with factory() as db:
        svc = PomodoroService(db)
        with pytest.raises(ActiveSessionExists) as ei:
            await svc.start_session()
        assert ei.value.existing_id == first.id


@pytest.mark.asyncio
async def test_start_invalid_surface_raises(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = PomodoroService(db)
        with pytest.raises(ValueError):
            await svc.start_session(surface="bogus")


# ---------------------------------------------------------------------------
# Pause / resume / pause_accumulated_seconds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_then_resume_accumulates_pause_seconds(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = PomodoroService(db)
        row = await svc.start_session()
        await svc.pause_session(row.id)
        # Backdate paused_at so resume sees a positive elapsed pause window.
        async with factory() as db2:
            target = await db2.get(PomodoroSessionModel, row.id)
            target.paused_at = datetime.now(UTC) - timedelta(seconds=42)
            await db2.commit()
    async with factory() as db:
        svc = PomodoroService(db)
        resumed = await svc.resume_session(row.id)
    assert resumed.status == "active"
    assert resumed.paused_at is None
    assert resumed.pause_accumulated_seconds >= 42


@pytest.mark.asyncio
async def test_resume_only_from_paused(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = PomodoroService(db)
        row = await svc.start_session()
        with pytest.raises(InvalidTransition):
            await svc.resume_session(row.id)


@pytest.mark.asyncio
async def test_pause_only_from_active(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = PomodoroService(db)
        row = await svc.start_session()
        await svc.complete_session(row.id)
        with pytest.raises(InvalidTransition):
            await svc.pause_session(row.id)


# ---------------------------------------------------------------------------
# Complete / abandon
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_sets_status_and_completed_at(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = PomodoroService(db)
        row = await svc.start_session()
        completed = await svc.complete_session(row.id)
    assert completed.status == "completed"
    assert completed.completed_at is not None


@pytest.mark.asyncio
async def test_complete_twice_raises(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = PomodoroService(db)
        row = await svc.start_session()
        await svc.complete_session(row.id)
    async with factory() as db:
        svc = PomodoroService(db)
        with pytest.raises(InvalidTransition):
            await svc.complete_session(row.id)


@pytest.mark.asyncio
async def test_abandon_sets_status(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = PomodoroService(db)
        row = await svc.start_session()
        abandoned = await svc.abandon_session(row.id)
    assert abandoned.status == "abandoned"


@pytest.mark.asyncio
async def test_complete_unknown_session_raises(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = PomodoroService(db)
        with pytest.raises(SessionNotFound):
            await svc.complete_session(str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_complete_from_paused_rolls_pause_window(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = PomodoroService(db)
        row = await svc.start_session()
        await svc.pause_session(row.id)
    async with factory() as db:
        target = await db.get(PomodoroSessionModel, row.id)
        target.paused_at = datetime.now(UTC) - timedelta(seconds=10)
        await db.commit()
    async with factory() as db:
        svc = PomodoroService(db)
        completed = await svc.complete_session(row.id)
    assert completed.status == "completed"
    assert completed.completed_at is not None
    assert completed.pause_accumulated_seconds >= 10


# ---------------------------------------------------------------------------
# get_active_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_session_none_initially(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = PomodoroService(db)
        assert await svc.get_active_session() is None


@pytest.mark.asyncio
async def test_get_active_session_returns_paused_row(test_db):
    _engine, factory = test_db
    async with factory() as db:
        svc = PomodoroService(db)
        row = await svc.start_session()
        await svc.pause_session(row.id)
    async with factory() as db:
        svc = PomodoroService(db)
        active = await svc.get_active_session()
    assert active is not None
    assert active.id == row.id
    assert active.status == "paused"


# ---------------------------------------------------------------------------
# Stats: today_count / streak / total_completed
# ---------------------------------------------------------------------------


def _seed_completed(session_factory, when: datetime):
    """Factory-build a completed pomodoro row at the given created_at timestamp."""

    async def _do() -> str:
        sid = str(uuid.uuid4())
        async with session_factory() as db:
            row = PomodoroSessionModel(
                id=sid,
                started_at=when,
                completed_at=when,
                focus_minutes=25,
                break_minutes=5,
                status="completed",
                surface="none",
                created_at=when,
                pause_accumulated_seconds=0,
            )
            db.add(row)
            await db.commit()
        return sid

    return _do


@pytest.mark.asyncio
async def test_stats_only_completed_count_total(test_db):
    _engine, factory = test_db
    now = datetime.now(UTC)

    # Seed 2 completed and 1 abandoned and 1 active.
    await _seed_completed(factory, now)()
    await _seed_completed(factory, now - timedelta(hours=1))()
    async with factory() as db:
        db.add(
            PomodoroSessionModel(
                id=str(uuid.uuid4()),
                status="abandoned",
                surface="none",
                started_at=now,
                created_at=now,
                pause_accumulated_seconds=0,
            )
        )
        db.add(
            PomodoroSessionModel(
                id=str(uuid.uuid4()),
                status="active",
                surface="none",
                started_at=now,
                created_at=now,
                pause_accumulated_seconds=0,
            )
        )
        await db.commit()

    async with factory() as db:
        svc = PomodoroService(db)
        stats = await svc.get_stats()

    assert stats["total_completed"] == 2
    assert stats["today_count"] == 2


@pytest.mark.asyncio
async def test_streak_three_consecutive_days(test_db):
    _engine, factory = test_db
    now = datetime.now(UTC)
    # Seed completions today, yesterday, two-days-ago.
    await _seed_completed(factory, now)()
    await _seed_completed(factory, now - timedelta(days=1))()
    await _seed_completed(factory, now - timedelta(days=2))()

    async with factory() as db:
        svc = PomodoroService(db)
        stats = await svc.get_stats()

    assert stats["streak_days"] == 3


@pytest.mark.asyncio
async def test_streak_breaks_on_gap(test_db):
    _engine, factory = test_db
    now = datetime.now(UTC)
    # Seed completions today and three days ago -> streak=1.
    await _seed_completed(factory, now)()
    await _seed_completed(factory, now - timedelta(days=3))()

    async with factory() as db:
        svc = PomodoroService(db)
        stats = await svc.get_stats()

    assert stats["streak_days"] == 1


@pytest.mark.asyncio
async def test_streak_zero_when_no_completion_today(test_db):
    _engine, factory = test_db
    now = datetime.now(UTC)
    # Only yesterday and the day before.
    await _seed_completed(factory, now - timedelta(days=1))()
    await _seed_completed(factory, now - timedelta(days=2))()

    async with factory() as db:
        svc = PomodoroService(db)
        stats = await svc.get_stats()

    assert stats["streak_days"] == 0
    assert stats["today_count"] == 0
    assert stats["total_completed"] == 2
