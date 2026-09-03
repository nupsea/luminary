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


# A write transaction held longer than this is reported with the statement that
# opened it. `busy_timeout` is 5s, so every other writer fails at ~5.2s while one
# is held open; measured on synthetic writers, a 4.5s hold blocks nobody and a
# 6.0s hold blocks all six. Nothing measured this before, which is why
# "database is locked" could name only its victims and never its cause.
_WRITE_HOLD_WARN_S = 3.0

_WRITE_SQL = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")


def _track_write_holds(engine) -> None:
    """Report which statement held the SQLite write lock, and for how long."""
    open_writes: dict[int, tuple[float, str]] = {}

    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        head = statement.lstrip()[:6].upper()
        if head.startswith(_WRITE_SQL) and id(conn) not in open_writes:
            open_writes[id(conn)] = (time.perf_counter(), " ".join(statement.split())[:120])

    def _finish(conn, *, held_lock: bool) -> None:
        started = open_writes.pop(id(conn), None)
        if started is None:
            return
        elapsed = time.perf_counter() - started[0]
        if elapsed < _WRITE_HOLD_WARN_S:
            return
        # Only a transaction that COMMITTED actually held the lock. One that
        # rolled back spent that time waiting for it and then failing, and
        # reporting it as a holder inverts cause and effect: a first version of
        # this logged 29 "holders", every one of them 5.2-5.4s -- busy_timeout
        # to the decimal -- which is the signature of victims, not a holder.
        logger.warning(
            "sqlite write %s %.2fs: %s",
            "lock HELD for" if held_lock else "BLOCKED for",
            elapsed,
            started[1],
        )

    event.listen(engine, "before_cursor_execute", _before)
    event.listen(engine, "commit", lambda conn: _finish(conn, held_lock=True))
    event.listen(engine, "rollback", lambda conn: _finish(conn, held_lock=False))


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
    _track_write_holds(engine.sync_engine)
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
