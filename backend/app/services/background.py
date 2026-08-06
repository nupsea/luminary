"""Fire-and-forget task scheduling with a strong reference and crash logging."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)


def fire_and_forget(
    coro: Coroutine[Any, Any, Any],
    registry: set[asyncio.Task],  # type: ignore[type-arg]
    *,
    label: str = "background task",
) -> asyncio.Task:  # type: ignore[type-arg]
    """Schedule `coro`, holding a strong ref in `registry` until it finishes.

    asyncio only holds a weak reference to a running task, so a bare
    create_task can be garbage-collected mid-flight. A crash is logged rather
    than discarded: an unobserved task's exception is otherwise never raised
    anywhere.

    The caller supplies `registry` because some modules count their own
    in-flight tasks.
    """
    task = asyncio.create_task(coro)
    registry.add(task)

    def _on_done(finished: asyncio.Task) -> None:  # type: ignore[type-arg]
        registry.discard(finished)
        if finished.cancelled():
            return
        exc = finished.exception()
        if exc is not None:
            logger.error("%s crashed", label, exc_info=exc)

    task.add_done_callback(_on_done)
    return task
