"""Quitting must not wait five minutes behind one background thread.

`asyncio.Runner.close()` joins the loop's default executor for
`THREAD_JOIN_TIMEOUT` -- 300 seconds -- and every `asyncio.to_thread` call runs
there (I-40). uvicorn closes its loop the same way, so an embed or a model load
still in flight could hold a desktop quit for five minutes, against the lifespan's
own stated requirement that quitting be quick. `_release_default_executor` bounds
that wait and then stops waiting.

**These tests must not measure the test harness.** `conftest` patches
`BaseEventLoop.shutdown_default_executor` to bound the same join for the suite, so
a test that left the patch in place would pass on the harness's bound whether or
not the product had one. Both tests below restore the stdlib method first, which
is the only way the assertion is about `app.main`.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app

# Long enough that waiting it out is unmistakable against a one-second grace.
_HELD_S = 6.0
_GRACE_S = 1.0


@pytest.fixture
def stdlib_executor_join(monkeypatch):
    """Undo conftest's suite-wide bound, so the product's own bound is what runs."""
    installed = asyncio.base_events.BaseEventLoop.shutdown_default_executor
    original = installed.__globals__.get("_original_shutdown_default_executor")
    assert original is not None, (
        "conftest no longer wraps shutdown_default_executor; this test needs the "
        "stdlib method to prove app.main is what bounds the quit"
    )
    monkeypatch.setattr(
        asyncio.base_events.BaseEventLoop, "shutdown_default_executor", original
    )


def _quit_seconds_with_thread_work_in_flight() -> float:
    """Seconds to leave the app with a thread parked in the default executor."""

    async def _fire_and_forget() -> None:
        asyncio.get_running_loop().run_in_executor(None, time.sleep, _HELD_S)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        client.portal.call(_fire_and_forget)
        time.sleep(0.3)
        started = time.monotonic()
    return time.monotonic() - started


def test_quit_does_not_wait_out_background_thread_work(
    stdlib_executor_join, monkeypatch
):
    monkeypatch.setattr(main_module, "_EXECUTOR_RELEASE_GRACE_S", _GRACE_S)

    elapsed = _quit_seconds_with_thread_work_in_flight()

    assert elapsed < _HELD_S / 2, (
        f"quitting took {elapsed:.1f}s for {_HELD_S}s of background work. "
        "Unbounded, the desktop supervisor gives up and SIGKILLs instead, which "
        "kills a mid-write thread with no grace at all."
    )


def test_without_the_release_the_quit_waits_it_out(stdlib_executor_join, monkeypatch):
    """The check firing: remove the release and the 300s join is what runs."""

    async def _noop() -> None:
        return

    monkeypatch.setattr(main_module, "_release_default_executor", _noop)

    elapsed = _quit_seconds_with_thread_work_in_flight()

    assert elapsed >= _HELD_S * 0.8, (
        f"quit returned in {elapsed:.1f}s without the release, so the "
        f"{_HELD_S}s of work was not actually in flight and the test above "
        "proves nothing"
    )
