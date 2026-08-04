"""The desktop shell's death switch.

A backend that outlives its shell keeps Kuzu's exclusive lock and blocks the
user's next launch, so this has to arm when asked -- and stay out of the way
for `make dev`, tests and CLI use, where there is no shell at all.
"""

import os

from app.parent_watch import _still_there, watch_parent


def test_no_parent_pid_means_no_watcher(monkeypatch):
    monkeypatch.delenv("LUMINARY_PARENT_PID", raising=False)
    assert watch_parent() is None


def test_malformed_or_impossible_pids_are_ignored(monkeypatch):
    for value in ["", "   ", "not-a-pid", "0", "1", "-4"]:
        monkeypatch.setenv("LUMINARY_PARENT_PID", value)
        assert watch_parent() is None, value


def test_a_real_parent_pid_starts_a_daemon_thread(monkeypatch):
    monkeypatch.setenv("LUMINARY_PARENT_PID", str(os.getppid()))
    thread = watch_parent()
    assert thread is not None
    # Daemon, so a wedged watcher can never keep the process alive.
    assert thread.daemon


def test_our_own_parent_is_recognised_as_present():
    assert _still_there(os.getppid())


def test_a_process_that_is_not_our_parent_counts_as_gone():
    # Whatever pid 2 is, it is not this process's parent, so the watcher must
    # treat it as gone rather than waiting forever on a stranger.
    assert not _still_there(2)
