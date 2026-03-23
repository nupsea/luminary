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

import pytest


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


# ---------------------------------------------------------------------------
# Deterministic service stubs live in tests/stubs.py (Belief #25)
# ---------------------------------------------------------------------------
# Test files import directly: from stubs import MockLLMService
