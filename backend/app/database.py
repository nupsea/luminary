import logging
import time
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from app.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def get_db_url() -> str:
    settings = get_settings()
    data_dir = Path(settings.DATA_DIR).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{data_dir}/luminary.db"


def _enable_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ARG001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    # synchronous stays at WAL's default of FULL, and cache_size/temp_store stay
    # at their defaults. All three were proposed as "zero risk, high impact" and
    # measured instead, inside the container on the real data volume:
    #
    #   commit cost   FULL 0.960 ms   NORMAL 0.005 ms   (400 commits)
    #   full ingest   FULL 137s/139s  NORMAL 157s/146s  (same PDF, same image)
    #
    # NORMAL is ~190x cheaper per commit and bought nothing end to end, because
    # commits are not a meaningful share of ingest -- that is GLiNER and the
    # embedder. Trading durability for an unmeasurable gain is not a trade.
    #
    # cache_size=-64000 was rejected outright: the pragma is PER CONNECTION and
    # make_engine below pools up to 30 (pool_size 10 + max_overflow 20), so it
    # allows ~1.9GB of page cache on hosts already measured at ~7.7GB of demand
    # against a 7.8GB Docker VM.
    #
    # The premise offered for all three -- that fsync crosses a VirtioFS
    # boundary -- describes a bind mount. `luminary-data` is a named volume and
    # lives inside the VM's own filesystem.
    cursor.close()


# SQLite has one writer. `busy_timeout=5000` above means a second writer waits up
# to five seconds and then fails with "database is locked" -- which is what
# `POST /notes` did whenever something else held the write lock for longer (#88).
# The victim's traceback names the write that failed and says nothing about the
# transaction responsible, so the holder has to report itself.
#
# Warn at 2s: comfortably below the 5s at which somebody else's write is already
# failing, and above the ordinary case -- a full ingest commits in single-digit
# milliseconds (measured: 0.960ms per commit at synchronous=FULL, 400 commits).
_WRITE_HOLD_WARN_S = 2.0

# id(connection) -> (monotonic start, first write statement). Entries are removed
# on commit/rollback and reset on begin, so the map is bounded by the pool.
_write_holds: dict[int, tuple[float, str]] = {}


def _note_write(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001, PLR0913
    """Record when a connection's first write *completed*, i.e. when it got the lock.

    Timed after the statement rather than before it on purpose: before it, the
    clock would include any time spent waiting on `busy_timeout` for somebody
    else's lock, and a victim that waited and then succeeded would be reported as
    a holder. What this measures is the hold.
    """
    head = statement.lstrip()[:7].upper()
    if head.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
        _write_holds.setdefault(
            id(conn), (time.monotonic(), " ".join(statement.split())[:90])
        )


def _clear_write_hold(conn):
    _write_holds.pop(id(conn), None)


def _report_write_hold(conn, outcome: str) -> None:
    record = _write_holds.pop(id(conn), None)
    if record is None:
        return
    started, first_write = record
    held = time.monotonic() - started
    if held >= _WRITE_HOLD_WARN_S:
        logger.warning(
            "SQLite write lock held %.1fs before %s (busy_timeout is 5.0s, so "
            "another writer was failing after that). First write: %s",
            held,
            outcome,
            first_write,
        )


def make_engine(db_url: str | None = None):
    url = db_url or get_db_url()
    kwargs: dict = {}
    if ":memory:" in url:
        kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
        kwargs["pool_timeout"] = 60
        kwargs["pool_recycle"] = 300

    engine = create_async_engine(
        url,
        echo=False,
        **kwargs,
    )
    event.listen(engine.sync_engine, "connect", _enable_sqlite_pragmas)
    event.listen(engine.sync_engine, "begin", _clear_write_hold)
    event.listen(engine.sync_engine, "after_cursor_execute", _note_write)
    event.listen(engine.sync_engine, "commit", lambda c: _report_write_hold(c, "commit"))
    event.listen(engine.sync_engine, "rollback", lambda c: _report_write_hold(c, "rollback"))
    return engine


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db() -> AsyncSession:  # type: ignore[return]
    async with get_session_factory()() as session:
        yield session
