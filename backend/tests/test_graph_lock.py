"""Kuzu lock handling for the one-time graph import (I-24).

Kuzu's lock is an OS file lock the kernel releases when the holder dies, so a held lock
means a live process (an older Luminary still running). The import waits for it and
never clears it: the only thing clearing it could kill is a live process mid-write.
"""

import subprocess
import sys
import textwrap

import pytest

from app.services.graph_connection import GraphDatabaseLockedError, open_read_only


@pytest.fixture
def lock_holder(tmp_path):
    """A real second process holding the Kuzu lock. Mocking this would prove nothing."""
    db = tmp_path / "graph.kuzu"
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
        yield tmp_path, proc
    finally:
        proc.kill()
        proc.wait()


@pytest.mark.slow
def test_locked_database_raises_actionable_error_and_spares_the_holder(lock_holder):
    data_dir, proc = lock_holder

    with pytest.raises(GraphDatabaseLockedError) as exc:
        open_read_only(str(data_dir))

    assert "locked by another running process" in str(exc.value)
    # The holder must survive. Boot killing it is the bug being fixed.
    assert proc.poll() is None, "the lock holder was killed"


@pytest.mark.slow
def test_lock_is_released_when_holder_dies(lock_holder):
    # Why no stale-lock recovery is needed: SIGKILL leaves the holder no chance to
    # clean up, and the lock still clears.
    data_dir, proc = lock_holder
    proc.kill()
    proc.wait()

    open_read_only(str(data_dir))  # must not raise


def test_unrelated_runtime_errors_are_not_swallowed(tmp_path, monkeypatch):
    import app.services.graph_connection as gc

    def _boom(_path, **_kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(gc.kuzu, "Database", _boom)
    with pytest.raises(RuntimeError, match="disk on fire"):
        open_read_only(str(tmp_path))
