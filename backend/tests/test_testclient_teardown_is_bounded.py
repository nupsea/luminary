"""Leaving a `TestClient` context must not wait out background thread work.

`with TestClient(app)` ends in `asyncio.Runner.close()`, which joins the loop's
default executor for `asyncio.constants.THREAD_JOIN_TIMEOUT` -- **300 seconds**.
Every `asyncio.to_thread` call runs there (I-2 puts LanceDB and Kuzu in it, and
the embedder and GLiNER loads land there too), so a single fire-and-forget task
still inside one when the client exits parks teardown until that call returns.
At 300s that is past the 120s per-test timeout, so the session dies and the
report blames whichever test owned the client rather than the one that leaked.

Observed as a whole-suite hang on `master` at 8634011, surfacing in a different
test on each run.

The two tests below are a pair and neither means anything alone:
`test_teardown_does_not_wait_out_background_thread_work` shows teardown returning
early, and `test_the_bound_is_what_makes_it_early` removes the bound and shows the
same teardown waiting the work out. Without the second, the first would pass just
as happily against work that had already finished.
"""

import asyncio
import threading
import time

from fastapi.testclient import TestClient

from app.main import app

# The executor call the client leaks behind it. Long enough that waiting it out is
# unmistakable against a one-second grace, short enough that the negative test
# below stays well inside the 120s per-test timeout it is demonstrating.
_HELD_S = 6.0
_GRACE_S = 1.0


def _installed_join():
    """The wrapper conftest put on the loop class, and the globals it reads.

    Taken off the class rather than off an imported `conftest`: pytest owns the
    conftest module object, and `import conftest` can hand back a second copy whose
    globals the running wrapper never reads -- patching that copy changes nothing
    and the test passes for the wrong reason.
    """
    fn = asyncio.base_events.BaseEventLoop.shutdown_default_executor
    assert "_EXECUTOR_JOIN_GRACE_S" in fn.__globals__, (
        "the bounded executor join is not installed; conftest no longer patches "
        "BaseEventLoop.shutdown_default_executor"
    )
    return fn


def _exit_seconds_with_executor_work_in_flight() -> float:
    """Seconds `TestClient.__exit__` takes while a thread is parked in the executor.

    The work is fired without being awaited, deliberately: nothing holds it through
    a task, which is what rules out task-draining as a remedy. `portal.call` runs it
    on the portal's own loop, the way a router's fire-and-forget task does.
    """

    async def _fire_and_forget() -> None:
        asyncio.get_running_loop().run_in_executor(None, time.sleep, _HELD_S)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        client.portal.call(_fire_and_forget)
        # Let the executor thread actually pick the call up before we tear down.
        time.sleep(0.3)
        started = time.monotonic()
    return time.monotonic() - started


def test_teardown_does_not_wait_out_background_thread_work(monkeypatch):
    monkeypatch.setitem(_installed_join().__globals__, "_EXECUTOR_JOIN_GRACE_S", _GRACE_S)
    before = threading.active_count()

    elapsed = _exit_seconds_with_executor_work_in_flight()

    assert elapsed < _HELD_S / 2, (
        f"teardown took {elapsed:.1f}s for {_HELD_S}s of background work: the "
        "executor join is unbounded again, and the suite will hang on whichever "
        "test happens to leak next"
    )
    # The work was abandoned, not killed. Asserting it is still running is what
    # keeps this from passing because the call finished early on a fast machine.
    assert threading.active_count() > before


def test_the_bound_is_what_makes_it_early(monkeypatch):
    """Remove the bound and the same teardown waits the work out.

    This is the check firing. If it ever stops failing to return early, the first
    test is measuring nothing.
    """
    original = _installed_join().__globals__["_original_shutdown_default_executor"]
    monkeypatch.setattr(
        asyncio.base_events.BaseEventLoop, "shutdown_default_executor", original
    )

    elapsed = _exit_seconds_with_executor_work_in_flight()

    assert elapsed >= _HELD_S * 0.8, (
        f"teardown returned in {elapsed:.1f}s with the bound removed, so the "
        f"{_HELD_S}s of background work was not actually in flight and the "
        "positive test above proves nothing"
    )
