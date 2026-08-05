"""Exit when the desktop shell that started us is gone.

macOS has no `PR_SET_PDEATHSIG`, so a shell that crashes or is force-quit never
gets to stop its children. A surviving backend keeps Kuzu's exclusive file lock,
which does not degrade the next launch -- it blocks it outright. Polling the
parent is the only mechanism that still works when the shell had no opportunity
to run any code at all.

SIGTERM to ourselves rather than an immediate exit: uvicorn turns it into an
orderly shutdown, so the lifespan teardown runs and SQLite checkpoints its WAL.
"""

import logging
import os
import signal
import threading
import time

logger = logging.getLogger(__name__)

_POLL_SECONDS = 5.0


def _still_there(pid: int) -> bool:
    if os.getppid() != pid:
        # Reparented to launchd, so the original parent is already gone.
        return False
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
            os.kill(os.getpid(), signal.SIGTERM)
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
