"""The desktop shell's death switch.

A backend that outlives its shell keeps Kuzu's exclusive lock and blocks the
user's next launch, so this has to arm when asked -- and stay out of the way
for `make dev`, tests and CLI use, where there is no shell at all.
"""

import os
import platform

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


# The Windows trap
#
# `os.kill(pid, 0)` reads as a liveness probe on every platform and is one on
# Unix. On Windows CPython documents it as TerminateProcess with the exit code
# set to the signal, so the probe kills the desktop shell it is checking on --
# every five seconds, looking like a clean exit. No runner here is Windows and
# the shell has no Windows build, so a platform-pinned test is the whole guard.


def test_the_probe_never_calls_os_kill_on_windows(monkeypatch):
    from app import parent_watch

    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(parent_watch.os, "getppid", lambda: 4242)
    monkeypatch.setattr(parent_watch.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(parent_watch, "_windows_alive", lambda pid: True)

    assert parent_watch._still_there(4242) is True
    assert killed == [], "os.kill on Windows terminates the process it is asked about"


def test_the_windows_probe_answers_from_the_exit_code(monkeypatch):
    from app import parent_watch

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(parent_watch.os, "getppid", lambda: 4242)

    monkeypatch.setattr(parent_watch, "_windows_alive", lambda pid: False)
    assert parent_watch._still_there(4242) is False


def test_unix_still_probes_with_signal_zero(monkeypatch):
    """The change may not cost the platform that was already right."""
    from app import parent_watch

    probed: list[tuple[int, int]] = []
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(parent_watch.os, "getppid", lambda: 4242)
    monkeypatch.setattr(parent_watch.os, "kill", lambda pid, sig: probed.append((pid, sig)))

    assert parent_watch._still_there(4242) is True
    assert probed == [(4242, 0)]


def test_stopping_raises_the_signal_rather_than_killing_this_process(monkeypatch):
    """`os.kill(os.getpid(), SIGTERM)` is the same trap pointed inward.

    On Windows it is TerminateProcess against ourselves with exit code 15, so
    uvicorn never runs the lifespan teardown this module exists to trigger.
    """
    import signal as signal_mod

    from app import parent_watch

    raised: list[int] = []
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(signal_mod, "raise_signal", lambda sig: raised.append(sig))
    monkeypatch.setattr(parent_watch.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(parent_watch, "_still_there", lambda pid: False)
    monkeypatch.setattr(parent_watch.time, "sleep", lambda _s: None)

    parent_watch._watch(4242)

    assert raised == [signal_mod.SIGTERM]
    assert killed == []
