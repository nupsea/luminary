"""Kuzu lock handling.

Boot used to `lsof` the graph file and SIGTERM whatever held it, to clear a "stale
lock". Kuzu's lock is an exclusive OS file lock that the kernel releases when the
holder dies, so a stale lock cannot outlive its process -- the only thing that code
could ever kill was a LIVE process mid-write, which is how a graph database gets
corrupted. It is gone; a held lock now raises an actionable error instead.
"""

import subprocess
import sys
import textwrap

import pytest

from app.services.graph_connection import GraphDatabaseLockedError, _open_database


@pytest.fixture
def lock_holder(tmp_path):
    """A real second process holding the Kuzu lock. Mocking this would prove nothing."""
    db = tmp_path / "held.kuzu"
    src = textwrap.dedent(f"""
        import kuzu, time
        db = kuzu.Database(r"{db}")
        kuzu.Connection(db).execute("CREATE NODE TABLE IF NOT EXISTS T(id STRING PRIMARY KEY)")
        print("HOLDING", flush=True)
        time.sleep(60)
    """)
    proc = subprocess.Popen([sys.executable, "-c", src], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "HOLDING"
        yield db, proc
    finally:
        proc.kill()
        proc.wait()


@pytest.mark.slow
def test_locked_database_raises_actionable_error_and_spares_the_holder(lock_holder):
    db, proc = lock_holder

    with pytest.raises(GraphDatabaseLockedError) as exc:
        _open_database(str(db))

    assert "locked by another running process" in str(exc.value)
    # The holder must survive. Boot killing it is the bug being fixed.
    assert proc.poll() is None, "the lock holder was killed"


@pytest.mark.slow
def test_lock_is_released_when_holder_dies(lock_holder):
    # Why no stale-lock recovery is needed: SIGKILL leaves the holder no chance to
    # clean up, and the lock still clears.
    db, proc = lock_holder
    proc.kill()
    proc.wait()

    _open_database(str(db))  # must not raise


def test_unrelated_runtime_errors_are_not_swallowed(tmp_path, monkeypatch):
    import app.services.graph_connection as gc

    def _boom(_path):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(gc.kuzu, "Database", _boom)
    with pytest.raises(RuntimeError, match="disk on fire"):
        _open_database(str(tmp_path / "x.kuzu"))
