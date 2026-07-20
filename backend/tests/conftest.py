"""Session-scoped test isolation fixture.

Ensures all tests use an isolated temp directory for DATA_DIR instead of the
production ~/.luminary path.  This prevents:

  - Kuzu file lock conflicts when a dev backend is running concurrently
  - Accidental reads/writes to production SQLite, LanceDB, or Kuzu data

Individual test files may still monkeypatch DATA_DIR further (e.g. test_db
fixtures with in-memory SQLite).  The session fixture provides the safe
baseline: even tests that don't define their own DB fixture will never touch
~/.luminary.
"""

import asyncio
import os
import warnings
from unittest.mock import patch

import pytest
import pytest_asyncio

# Filter aiosqlite DeprecationWarning for Python 3.12+ datetime adapter
warnings.filterwarnings("ignore", category=DeprecationWarning, module="aiosqlite")


@pytest.fixture(scope="session", autouse=True)
def isolated_data_dir(tmp_path_factory):
    """Set DATA_DIR to a session-scoped temp directory for all tests.

    Runs once before any test; tears down after all tests complete.
    It is safe to run the full test suite alongside a live dev backend.
    """
    data_dir = str(tmp_path_factory.mktemp("luminary_test_data"))
    os.environ["DATA_DIR"] = data_dir
    # Disable Phoenix tracing so tests do not try to bind port 4317/6006.
    # This prevents conflicts when a live dev backend is running concurrently.
    os.environ["PHOENIX_ENABLED"] = "false"

    # Clear the settings LRU cache so get_settings() picks up the new env var.
    from app.config import get_settings

    get_settings.cache_clear()

    # Reset module-level singletons so they are (re)created against the temp
    # data_dir rather than whatever path they may have been initialised with.
    import app.database as db_module
    import app.services.graph as graph_module
    import app.services.vector_store as vs_module

    db_module._engine = None
    db_module._session_factory = None
    graph_module._graph_service = None
    vs_module._lancedb_service = None

    yield data_dir

    # Teardown: remove the env var and clear the settings cache so the next
    # process (or interactive session) is not affected.
    os.environ.pop("DATA_DIR", None)
    os.environ.pop("PHOENIX_ENABLED", None)
    from app.config import get_settings as _gs

    _gs.cache_clear()


@pytest.fixture(autouse=True)
def _reset_lancedb_singleton():
    """Drop the cached LanceDB service before each test.

    The service is a module-level singleton; without this it persists across
    the whole suite, so note/chunk vectors from 1676 tests pile into one
    instance until LanceDB spills to disk under memory pressure and errors
    (LanceError(IO): Spill) -- which flakes note/embed-adjacent tests. Resetting
    per test gives each a fresh, small store (recreated lazily against the
    current DATA_DIR; on-disk data for shared dirs is reopened intact). Kuzu is
    intentionally left alone to avoid file-lock churn from rapid reopens.
    """
    import app.services.vector_store as _vs_module

    _vs_module._lancedb_service = None
    yield


UNDRAINABLE_TASKS: list[str] = []


def _detach_from_loop_shutdown(task: asyncio.Task) -> None:
    """Remove a task from the registry that asyncio's loop-close routine walks.

    There is no public API: `_cancel_all_tasks()` reads `asyncio.all_tasks()`, so
    unregistering the task is the only way to stop it being waited on.
    """
    try:
        import _asyncio

        _asyncio._unregister_task(task)
        return
    except Exception:  # noqa: BLE001 - pure-Python asyncio has no C accelerator
        pass
    try:
        asyncio.tasks._all_tasks.discard(task)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - best effort; a hang here is worse than a miss
        pass


def pytest_terminal_summary(terminalreporter):
    if not UNDRAINABLE_TASKS:
        return
    terminalreporter.section("Leaked background tasks (ignored cancellation)", sep="=")
    for entry in UNDRAINABLE_TASKS:
        terminalreporter.write_line(f"  {entry}")


def _task_module(task: asyncio.Task) -> str:
    """Module that a task's coroutine was defined in, or "" if it cannot be read."""
    coro = task.get_coro()
    frame = getattr(coro, "cr_frame", None) or getattr(coro, "ag_frame", None)
    if frame is None:
        return ""
    return str(frame.f_globals.get("__name__", ""))


@pytest_asyncio.fixture(autouse=True)
async def _drain_leaked_tasks(request):
    """Cancel any fire-and-forget task the test spawned, while its loop is still alive.

    Routers fire ~12 kinds of background task (document pre-generate, tag enrichment,
    note embedding/description, XP awards...). In the app that is correct: the loop
    outlives them. Under pytest-asyncio each test gets its OWN loop, so a task spawned
    by test A is bound to loop A -- and whatever the task is awaiting (an LLM call, an
    embedder load, a DB handle) resolves on a loop that is about to close. The task then
    surfaces in a LATER test's teardown, where the finalizer awaits a future that can
    never complete, and the suite hangs at the 120s timeout blaming an innocent test.

    Cancelling here, inside the owning loop, is the only point where cancellation can
    actually be processed.

    Only tasks running OUR code are cancelled. Tests marked @pytest.mark.anyio are driven
    by anyio's TestRunner, which runs the test -- and this very fixture -- from its own
    asyncio tasks. Cancelling everything except `current` therefore cancelled the harness
    running the test, which surfaced as CancelledError at teardown of every anyio test and
    as "previous item was not torn down properly" in the tests after it.
    """
    yield
    current = asyncio.current_task()
    leaked = [
        t
        for t in asyncio.all_tasks()
        if t is not current and not t.done() and _task_module(t).startswith("app.")
    ]
    for t in leaked:
        t.cancel()
    if leaked:
        # Bounded: a task stuck in a thread executor cannot be cancelled, and waiting
        # forever for it would recreate the hang this fixture exists to prevent.
        await asyncio.wait(leaked, timeout=5)

    # Anything still alive ignored its cancellation -- typically sitting in a thread
    # executor (GLiNER/NER, embedding) where cancellation cannot land until the call
    # returns. Left registered, it is then gathered by the loop-close routine WITHOUT a
    # timeout, so one such task hangs the run until the 120s session timeout kills it,
    # blaming whichever test was running. Detaching lets teardown finish; the task is
    # already cancelled and its loop is going away regardless. Reported at session end
    # so the leak stays visible rather than silently tolerated.
    survivors = [t for t in leaked if not t.done()]
    for t in survivors:
        UNDRAINABLE_TASKS.append(f"{request.node.nodeid} :: {_task_module(t)} :: {t!r}")
        _detach_from_loop_shutdown(t)


@pytest.fixture(autouse=True)
def _no_real_library_summary_generation():
    """Stop summary_node's fire-and-forget task from outliving the test that spawned it.

    scope='all' with no cached library summary fires
    `asyncio.create_task(_generate_library_summary_task())`. In the app that is
    correct -- it warms the summary for next time. In tests it is a live task holding
    an LLM call, and pytest-asyncio gives each test its own event loop: the task
    outlives its test, and the NEXT loop close calls _cancel_all_tasks, which cancels
    then gathers. An LLM call sitting in a thread executor cannot be cancelled, so the
    gather blocks until the 120s per-test timeout kills the whole session -- attributed
    to whatever unlucky test happened to be running (seen on CI in test_note_title, and
    locally ~30% into the suite; the culprit is neither).

    Neutralising the coroutine keeps the create_task call observable -- tests asserting
    that generation was fired still pass -- while the task completes instantly.
    """
    async def _noop() -> None:
        return

    with patch("app.runtime.chat_nodes.summary._generate_library_summary_task", _noop):
        yield


# Deterministic service stubs live in tests/stubs.py (Belief #25)
# Test files import directly: from stubs import MockLLMService
