"""Exit when the desktop shell that started us is gone.

macOS has no `PR_SET_PDEATHSIG`, so a shell that crashes or is force-quit never
gets to stop its children. A surviving backend keeps Kuzu's exclusive file lock,
which does not degrade the next launch -- it blocks it outright. Polling the
parent is the only mechanism that still works when the shell had no opportunity
to run any code at all.

`raise_signal(SIGTERM)` rather than an immediate exit: uvicorn turns it into an
orderly shutdown, so the lifespan teardown runs and SQLite checkpoints its WAL.

**`os.kill` is not a liveness probe on Windows.** CPython documents it: any
signal other than `CTRL_C_EVENT` or `CTRL_BREAK_EVENT` "will cause the process to
be unconditionally killed by the TerminateProcess API, and the exit code will be
set to *sig*". So `os.kill(parent, 0)` -- which reads as a probe on every
platform and is one on Unix -- terminates the desktop shell there, with exit code
0, every five seconds, and the shell looks like it quit cleanly. `os.kill(self,
SIGTERM)` is the same trap pointed inward: it would terminate this process with
exit code 15 and skip the drain the docstring above promises.

Latent rather than live only because the shell is the sole setter of
`LUMINARY_PARENT_PID` and has no Windows build yet. Guarded by
`tests/test_parent_watch.py`.
"""

import ctypes
import logging
import os
import platform
import signal
import threading
import time

logger = logging.getLogger(__name__)

_POLL_SECONDS = 5.0


# `GetExitCodeProcess` reports this while the process is running. A process that
# genuinely exits with 259 is indistinguishable from a live one, which is the
# documented cost of this API and not worth a second handle to avoid here.
_STILL_ACTIVE = 259
# Enough to ask whether a process exists without the right to affect it, so a
# shell running at a different integrity level still answers.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _windows_alive(pid: int) -> bool:
    """Whether *pid* is running, asked without killing it."""
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]  # noqa: PLC0415
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Gone, or never ours to see. Either way we stop.
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _still_there(pid: int) -> bool:
    if os.getppid() != pid:
        # Reparented to launchd, so the original parent is already gone.
        return False
    if platform.system() == "Windows":
        return _windows_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Alive, just not ours to signal.
        return True
    return True


def _watch(pid: int) -> None:
    while True:
        time.sleep(_POLL_SECONDS)
        if not _still_there(pid):
            logger.warning("desktop shell (pid %s) is gone, shutting down", pid)
            # Never `os.kill(os.getpid(), SIGTERM)`: on Windows that is
            # TerminateProcess against ourselves and the drain never runs.
            signal.raise_signal(signal.SIGTERM)
            return


def watch_parent() -> threading.Thread | None:
    """Start watching if the desktop shell asked us to.

    A no-op for `make dev`, tests and CLI use, where no parent pid is set.
    """
    raw = os.environ.get("LUMINARY_PARENT_PID", "").strip()
    if not raw:
        return None
    try:
        pid = int(raw)
    except ValueError:
        logger.warning("ignoring malformed LUMINARY_PARENT_PID %r", raw)
        return None
    if pid <= 1:
        return None

    thread = threading.Thread(target=_watch, args=(pid,), name="parent-watch", daemon=True)
    thread.start()
    logger.info("watching desktop shell pid %s", pid)
    return thread
