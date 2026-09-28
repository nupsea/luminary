"""The SQLite write-lock report names the transaction that held the lock, never its victims.

`database is locked` names the statement that failed. The report exists so the holder
names itself (#88, #157); a victim that waited out another writer's lock and then
succeeded must not appear as a holder, or the report points at the wrong code.
"""

import asyncio
import logging

import pytest
from sqlalchemy import text

import app.database as db


@pytest.fixture
def fast_threshold(monkeypatch):
    # 0.2s keeps the test short; the victim below waits ~0.5s, well past it.
    monkeypatch.setattr(db, "_WRITE_HOLD_WARN_S", 0.2)


async def _engine(tmp_path):
    engine = db.make_engine(f"sqlite+aiosqlite:///{tmp_path}/lock.db")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE IF NOT EXISTS t (x INTEGER)"))
    return engine


def _reports(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "write lock held" in r.getMessage()]


@pytest.mark.asyncio
async def test_a_long_write_transaction_reports_itself(tmp_path, caplog, fast_threshold):
    engine = await _engine(tmp_path)
    caplog.set_level(logging.WARNING, logger="app.database")
    async with engine.connect() as conn:
        await conn.execute(text("INSERT INTO t VALUES (1)"))
        await asyncio.sleep(0.4)
        await conn.commit()
    await engine.dispose()

    [report] = _reports(caplog)
    assert "before commit" in report
    assert "INSERT INTO t VALUES (1)" in report


@pytest.mark.asyncio
async def test_a_writer_that_only_waited_for_the_lock_is_not_reported(
    tmp_path, caplog, fast_threshold
):
    engine = await _engine(tmp_path)
    caplog.set_level(logging.WARNING, logger="app.database")
    victim_waited = 0.0

    async with engine.connect() as holder:
        await holder.execute(text("INSERT INTO t VALUES (1)"))

        async def victim():
            nonlocal victim_waited
            async with engine.connect() as conn:
                loop = asyncio.get_running_loop()
                t0 = loop.time()
                await conn.execute(text("INSERT INTO t VALUES (2)"))  # blocks on busy_timeout
                victim_waited = loop.time() - t0
                await conn.commit()

        task = asyncio.create_task(victim())
        await asyncio.sleep(0.5)
        await holder.commit()
        await task
    await engine.dispose()

    # The victim spent longer than the threshold waiting, yet only the holder reports.
    assert victim_waited > db._WRITE_HOLD_WARN_S
    reports = _reports(caplog)
    assert len(reports) == 1
    assert "VALUES (1)" in reports[0]
