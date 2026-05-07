"""Per-document async task registry for the ingestion pipeline.

Owns the lifecycle of every long-running ingestion task so the rest of the
backend can find, cancel, and await them by ``document_id``. Replaces the
unkeyed ``_background_tasks`` set that previously only served as a GC anchor
in :mod:`app.workflows.ingestion`.

Design notes:

- Single in-process registry. The app runs as a single FastAPI worker on the
  user's machine, so we don't need a distributed scheduler -- just enough
  bookkeeping to find a running task by document id.
- Strong references in ``_tasks`` prevent asyncio's weak-only tracking from
  collecting tasks mid-run.
- :meth:`cancel` injects ``CancelledError`` into the task and awaits its
  teardown with a bounded timeout so the caller (e.g. the delete endpoint)
  can safely free shared resources immediately afterwards without racing
  against in-flight DB writes from the workflow.
- Cancellation is cooperative. The ingestion graph hits an ``await`` at
  every node boundary (DB stage updates, embedder calls, LLM calls), so
  ``CancelledError`` surfaces within ~one stage. ``except Exception`` blocks
  in the workflow do **not** swallow it because :class:`asyncio.CancelledError`
  inherits from :class:`BaseException` since Python 3.8.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CANCEL_TIMEOUT_SECONDS = 10.0


class IngestionJobRegistry:
    """Tracks the running ingestion task for each document id."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def launch(
        self, document_id: str, coro: Coroutine[Any, Any, None]
    ) -> asyncio.Task[None]:
        """Schedule ``coro`` as the ingestion task for ``document_id``.

        If a task is already running for the same id, the new coroutine is
        closed (to avoid the "coroutine was never awaited" warning) and the
        existing task is returned. Callers that intentionally retry an errored
        ingestion should ensure the previous task has finished first.
        """
        existing = self._tasks.get(document_id)
        if existing is not None and not existing.done():
            logger.warning(
                "Ingestion task already running; reusing",
                extra={"document_id": document_id},
            )
            coro.close()
            return existing
        task = asyncio.create_task(coro, name=f"ingestion:{document_id}")
        self._tasks[document_id] = task
        task.add_done_callback(lambda t, did=document_id: self._on_done(did, t))
        return task

    def _on_done(self, document_id: str, task: asyncio.Task[None]) -> None:
        # Only remove if the stored task is still ours; a retry may have already
        # registered a replacement.
        if self._tasks.get(document_id) is task:
            self._tasks.pop(document_id, None)
        if task.cancelled():
            logger.info("Ingestion task cancelled", extra={"document_id": document_id})
            return
        exc = task.exception()
        if exc is not None:
            logger.warning(
                "Ingestion task ended with exception",
                extra={"document_id": document_id},
                exc_info=exc,
            )

    def get(self, document_id: str) -> asyncio.Task[None] | None:
        return self._tasks.get(document_id)

    def is_running(self, document_id: str) -> bool:
        task = self._tasks.get(document_id)
        return task is not None and not task.done()

    def active_document_ids(self) -> list[str]:
        return [did for did, t in self._tasks.items() if not t.done()]

    async def cancel(
        self,
        document_id: str,
        timeout: float = DEFAULT_CANCEL_TIMEOUT_SECONDS,
    ) -> bool:
        """Cancel the task for ``document_id`` and await its teardown.

        Returns ``True`` if a running task was cancelled within ``timeout``,
        ``False`` if no task was running or the task didn't finish in time.
        """
        task = self._tasks.get(document_id)
        if task is None or task.done():
            return False
        task.cancel()
        try:
            await asyncio.wait_for(_swallow_cancel(task), timeout=timeout)
        except TimeoutError:
            logger.warning(
                "Ingestion task did not finish cancelling within timeout",
                extra={"document_id": document_id, "timeout_s": timeout},
            )
            return False
        return True

    def reset(self) -> None:
        """Test helper: drop all tracked tasks without awaiting them."""
        self._tasks.clear()


async def _swallow_cancel(task: asyncio.Task[None]) -> None:
    """Await ``task`` to completion, suppressing ``CancelledError``.

    Other exceptions raised during teardown are intentionally swallowed; they
    are already logged by :meth:`IngestionJobRegistry._on_done` and are not the
    caller's concern when cancelling for cleanup.
    """
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:  # noqa: BLE001 -- intentional broad catch, see docstring
        pass


_registry: IngestionJobRegistry | None = None


def get_ingestion_jobs() -> IngestionJobRegistry:
    """Return the process-wide :class:`IngestionJobRegistry` singleton."""
    global _registry
    if _registry is None:
        _registry = IngestionJobRegistry()
    return _registry
