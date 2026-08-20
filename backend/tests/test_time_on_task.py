"""Time-on-task accrual: what a heartbeat is worth, and what it is not."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import TimeOnTaskModel
from app.services.time_on_task_service import (
    MAX_CREDITED_GAP_SECONDS,
    TimeOnTaskService,
)


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory
    yield engine, factory

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    await engine.dispose()


# The two cases that bracket the ceiling, as literals rather than as arithmetic
# on the constant under test: one slow round trip on a busy machine is real time
# on task, a minute away from the desk is not.
_A_SLOW_ROUND_TRIP = 20
_AWAY_FROM_THE_DESK = 60


async def _age_last_beat(factory, seconds: float) -> None:
    """Backdate the open interval so the next beat sees a gap of `seconds`."""
    async with factory() as s:
        row = (await s.execute(select(TimeOnTaskModel))).scalars().one()
        row.last_beat_at = datetime.now(UTC) - timedelta(seconds=seconds)
        await s.commit()


@pytest.mark.anyio
async def test_the_first_beat_credits_nothing(test_db):
    """There is nothing to measure from until a second sample arrives."""
    _, factory = test_db
    async with factory() as s:
        assert await TimeOnTaskService(s).beat("document", "doc-1") == 0


@pytest.mark.anyio
async def test_a_continuous_gap_is_credited(test_db):
    """20s is one slow round trip on a busy machine -- real time on task."""
    _, factory = test_db
    async with factory() as s:
        await TimeOnTaskService(s).beat("document", "doc-1")

    await _age_last_beat(factory, _A_SLOW_ROUND_TRIP)

    async with factory() as s:
        assert await TimeOnTaskService(s).beat("document", "doc-1") == _A_SLOW_ROUND_TRIP
        row = (await s.execute(select(TimeOnTaskModel))).scalars().one()
        assert row.seconds == _A_SLOW_ROUND_TRIP


@pytest.mark.anyio
async def test_the_ceiling_sits_between_its_two_bracketing_cases():
    """Pins the constant against the cases that chose it.

    Written after the first version of these tests derived its gap *from* the
    constant, so raising the ceiling raised the gap too and the check could not
    fail however wrong the value became.
    """
    assert _A_SLOW_ROUND_TRIP < MAX_CREDITED_GAP_SECONDS < _AWAY_FROM_THE_DESK


@pytest.mark.anyio
async def test_a_gap_too_long_to_be_continuous_credits_nothing(test_db):
    """The other bracket: the tab was hidden or the user left.

    Crediting it would report attention nobody paid, which is the whole reason
    the ceiling exists. A new interval starts instead of extending the old one.
    """
    _, factory = test_db
    async with factory() as s:
        await TimeOnTaskService(s).beat("note", "note-1")

    await _age_last_beat(factory, _AWAY_FROM_THE_DESK)

    async with factory() as s:
        assert await TimeOnTaskService(s).beat("note", "note-1") == 0
        rows = (await s.execute(select(TimeOnTaskModel))).scalars().all()
        assert len(rows) == 2, "a discontinuous beat opens a new interval"
        assert sum(r.seconds for r in rows) == 0


@pytest.mark.anyio
async def test_beats_extend_one_interval_rather_than_adding_a_row_each(test_db):
    """A session costs about one row, not one per sample."""
    _, factory = test_db
    async with factory() as s:
        await TimeOnTaskService(s).beat("study", None)
    for _ in range(3):
        await _age_last_beat(factory, 15)
        async with factory() as s:
            await TimeOnTaskService(s).beat("study", None)

    async with factory() as s:
        rows = (await s.execute(select(TimeOnTaskModel))).scalars().all()
        assert len(rows) == 1
        assert rows[0].seconds == 45


@pytest.mark.anyio
async def test_activities_are_accrued_separately(test_db):
    """The hub splits a week four ways; one bucket would make that undrawable."""
    _, factory = test_db
    async with factory() as s:
        svc = TimeOnTaskService(s)
        await svc.beat("document", "doc-1")
        await svc.beat("note", "note-1")

    async with factory() as s:
        rows = (await s.execute(select(TimeOnTaskModel))).scalars().all()
        for row in rows:
            row.last_beat_at = datetime.now(UTC) - timedelta(seconds=10)
        await s.commit()

    async with factory() as s:
        svc = TimeOnTaskService(s)
        await svc.beat("document", "doc-1")
        await svc.beat("note", "note-1")
        totals = await svc.seconds_by_activity()

    assert totals["document"] == 10
    assert totals["note"] == 10
    # Zero-filled: a missing slice must not be read as a measured zero.
    assert totals["review"] == 0
    assert totals["study"] == 0


@pytest.mark.anyio
async def test_an_unknown_activity_is_refused(test_db):
    """An activity the pie cannot draw is a client bug, not a silent row."""
    _, factory = test_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post(
            "/engagement/heartbeat", json={"activity": "doomscrolling", "member_id": None}
        )
    assert resp.status_code == 422

    async with factory() as s:
        assert (await s.execute(select(TimeOnTaskModel))).scalars().all() == []


@pytest.mark.anyio
async def test_the_endpoint_records_a_beat(test_db):
    _, factory = test_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (
            await c.post(
                "/engagement/heartbeat",
                json={"activity": "document", "member_id": str(uuid.uuid4())},
            )
        ).json()

    assert body["seconds_credited"] == 0
    assert body["heartbeat_seconds"] > 0

    async with factory() as s:
        assert len((await s.execute(select(TimeOnTaskModel))).scalars().all()) == 1
