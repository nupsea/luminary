"""Stopping this process the way a signal would, for a host that has no signal.

The desktop shell terminates the backend and Ollama together. On Unix that is a
SIGTERM to the process group, and `lifespan`'s shutdown runs: the enrichment
worker drains, ingestion jobs cancel, and every task registry is emptied before
the database closes. **Windows has no SIGTERM.** Terminating the process instead
skips all of that, so post-ingest work is cut mid-write and SQLite, LanceDB and
Kuzu are left disagreeing -- the divergence class of #65, landed on the platform
with the least testing.

So the shell asks over HTTP, waits, and only then terminates. What arrives here
raises SIGTERM against this process, which is a signal uvicorn installs a handler
for on Windows as well as Unix: it sets `should_exit`, the serve loop unwinds and
lifespan shuts down normally. The Job Object stays the crash net for the case
where nothing gets to ask.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import signal

from app.config import get_settings
from app.exceptions import Forbidden

logger = logging.getLogger(__name__)

# Long enough for the response to reach the caller, short enough that quitting
# does not read as a hang. The shell waits `TERM_GRACE` (6s) regardless.
_SHUTDOWN_DELAY_S = 0.25


def _raise_term() -> None:
    """Deliver the signal. Indirected so a test can hold it without a kill."""
    logger.info("Shutdown requested over HTTP; raising SIGTERM against this process")
    signal.raise_signal(signal.SIGTERM)


def request_shutdown(token: str | None) -> None:
    """Verify the caller is the shell that spawned us, then stop.

    Refuses identically whether the token is wrong or none was ever configured.
    Those are the same answer to the caller and distinguishing them would say
    whether this install has a secret worth guessing.
    """
    expected = get_settings().LUMINARY_SHUTDOWN_TOKEN
    if not expected or not token or not secrets.compare_digest(token, expected):
        raise Forbidden("Shutdown is not available to this caller.")

    asyncio.get_running_loop().call_later(_SHUTDOWN_DELAY_S, _raise_term)
