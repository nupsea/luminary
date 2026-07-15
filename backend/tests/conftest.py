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

import os
import warnings
from unittest.mock import patch

import pytest

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
