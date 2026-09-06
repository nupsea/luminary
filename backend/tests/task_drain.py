"""Bounded draining of fire-and-forget tasks in test teardown.

Five fixtures had grown the same body: cancel every task in a router's registry,
then `await asyncio.gather(*pending, return_exceptions=True)` with no timeout.
That is the shape `EnrichmentQueueWorker.stop()` was fixed for in `e648598` --
a task inside `asyncio.to_thread` cannot observe cancellation until the blocking
call returns, so the gather waits out an embed or a model load. `POST /notes`
schedules exactly such a task (`notes_service` embeds through
`run_in_executor`), and three of the five fixtures drain the notes registry.

Waiting forever in a fixture finalizer costs the whole session, not one test: it
blows the 120s per-test timeout, pytest kills the run, and the report names
whichever test owned the fixture rather than the one that leaked the work.
Observed on `test_e2e_upload.py` twice, intermittently, because whether a task
happens to be inside a `to_thread` at teardown is a matter of timing.

This exists as a helper rather than a fixed-up copy in each file so the next
fixture to need it cannot reintroduce the unbounded version by copying a
neighbour.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# Long enough for an in-flight DB write or a short embed to finish on its own,
# short enough that five of them cannot approach the 120s per-test timeout.
DRAIN_TIMEOUT_S = 5.0


async def drain_background_tasks(registry: set, timeout: float = DRAIN_TIMEOUT_S) -> None:
    """Cancel everything in *registry*, wait briefly, then let go.

    Empties the registry whether or not the tasks finished: a task that ignored
    cancellation is sitting in a thread and will end when its call returns, and
    holding a reference to it only keeps the next test's teardown waiting too.
    """
    pending = [task for task in list(registry) if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        done, _unfinished = await asyncio.wait(pending, timeout=timeout)
        for task in done:
            if not task.cancelled():
                # Retrieved so a crash is reported as the task's own failure
                # rather than surfacing later as "Task exception was never
                # retrieved" against whatever test happens to be running.
                task.exception()
    registry.clear()


# Disposing an engine awaits each pooled connection's close, and aiosqlite hands
# that result back on the loop that OPENED the connection. Across per-test loops
# that loop may be gone, so the future never completes and the fixture finalizer
# waits for it forever -- the 120s timeout then kills the session and blames the
# test that owned the fixture.
#
# Observed as a recurring `test_e2e_upload` timeout whose thread dump showed every
# aiosqlite worker idle: nothing was slow, something was simply never going to be
# answered. Bounded here so a stranded connection costs one fixture a few seconds
# instead of costing the run.
DISPOSE_TIMEOUT_S = 10.0


async def dispose_engine(engine, timeout: float = DISPOSE_TIMEOUT_S) -> None:
    """Dispose *engine*, giving up rather than waiting on a stranded connection."""
    try:
        await asyncio.wait_for(engine.dispose(), timeout=timeout)
    except TimeoutError:
        logger.warning(
            "engine.dispose() did not finish within %.0fs; abandoning its pool. A "
            "pooled connection is waiting on a loop that is already gone.",
            timeout,
        )
