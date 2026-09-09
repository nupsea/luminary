"""Fire-and-forget task scheduling, and the registries shutdown drains."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

# Every fire-and-forget registry in the process, keyed by the module that owns it.
_REGISTRIES: dict[str, set[asyncio.Task]] = {}  # type: ignore[type-arg]


def task_registry(name: str) -> set[asyncio.Task]:  # type: ignore[type-arg]
    """A fire-and-forget registry that shutdown can find.

    Ten modules declared `set()` directly and `lifespan` drained two of them, so
    note, flashcard and tag background work kept running against a database that
    was closing underneath it -- the same defect whose ingestion half is already
    described in `main.lifespan`, left standing everywhere else because each new
    registry had to be remembered and added there by hand.

    Declaring through here is what makes a registry visible to shutdown. A bare
    `set()` is invisible, which is why `tests/test_background_registries.py` fails
    CI when one appears.
    """
    return _REGISTRIES.setdefault(name, set())


def all_pending() -> set[asyncio.Task]:  # type: ignore[type-arg]
    """Every tracked task still running, across every registry."""
    return {task for reg in _REGISTRIES.values() for task in reg if not task.done()}


def clear_registries() -> None:
    """Drop references to finished-with tasks. Called after shutdown drains them."""
    for reg in _REGISTRIES.values():
        reg.clear()


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
