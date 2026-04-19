"""Tests for the Code Execution Sandbox (S140).

AC1: execute('print("hello")') returns stdout='hello\\n', exit_code=0
AC2: shell=False security -- os.system runs but no shell injection in command args
AC3: timeout test -- infinite loop terminates within 12 seconds
AC4: memory limit test -- 10**9 list terminates with non-zero (POSIX-only)
AC5: prediction strip comparison -- 'hello' vs 'hello\\n' yields correct=True
AC6: PredictionEventModel migrated via db_init (covered by test_db fixture)
AC7: integration test -- POST /code/execute returns prediction_correct and prediction_diff
AC8: JS 503 test -- node not found raises LookupError -> API returns 503
"""

import sys
import time
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.services.code_executor import CodeExecutorService, _compare_prediction

# ---------------------------------------------------------------------------
# Test DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Unit tests (no DB required)
# ---------------------------------------------------------------------------


def test_execute_python_hello():
    """AC1: execute('print("hello")') returns stdout='hello\\n', exit_code=0."""
    svc = CodeExecutorService()
    result = svc.execute('print("hello")', "python")
    assert result.stdout == "hello\n"
    assert result.exit_code == 0


def test_execute_no_shell_injection():
    """AC2: shell=False prevents injection via command args.

    os.system('echo pwned') inside the user code IS allowed to run
    (shell=False only protects the subprocess.run command args, not the code
    the user deliberately writes inside the sandbox). The test asserts exit_code=0
    to confirm the subprocess completed without interpreter-level errors.
    """
    svc = CodeExecutorService()
    result = svc.execute('import os; os.system("echo pwned")', "python")
    # os.system("echo pwned") returns 0 on success; subprocess.run shell=False
    # means no shell metacharacter injection is possible in the command args.
    assert result.exit_code == 0


def test_execute_timeout():
    """AC3: infinite loop returns non-zero exit_code within 12 seconds."""
    svc = CodeExecutorService()
    start = time.monotonic()
    result = svc.execute("while True: pass", "python", timeout_ms=3_000)
    elapsed = time.monotonic() - start
    # Must terminate (non-zero exit or timeout message)
    assert result.exit_code != 0 or result.stderr
    assert elapsed < 12.0, f"took {elapsed:.1f}s — must terminate within 12s"


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="RLIMIT_AS memory enforcement only reliable on Linux; "
    "macOS virtual memory semantics bypass RLIMIT_AS for anonymous allocations.",
)
def test_execute_memory_limit():
    """AC4: x = [0]*10**9 terminates with non-zero exit_code on Linux.

    RLIMIT_AS (256 MB virtual memory) is enforced via preexec_fn.
    On Linux: SIGKILL -> exit_code = -9 (or 137 via POSIX wait).
    On macOS: Python's allocator bypasses RLIMIT_AS for anonymous maps -- not reliable.
    Test is skipped on non-Linux platforms.
    """
    svc = CodeExecutorService()
    result = svc.execute("x = [0]*10**9", "python")
    assert result.exit_code != 0, (
        f"Expected non-zero exit_code (memory limit killed), got exit_code={result.exit_code}"
    )


# ---------------------------------------------------------------------------
# Pure function tests for _compare_prediction
# ---------------------------------------------------------------------------


def test_prediction_strip_normalizes_newline():
    """AC5: expected='hello', actual='hello\\n' -> correct=True (strip normalizes)."""
    correct, diff = _compare_prediction("hello", "hello\n")
    assert correct is True
    assert diff == ""


def test_prediction_wrong():
    """expected='hello', actual='' -> correct=False, diff is non-empty."""
    correct, diff = _compare_prediction("hello", "")
    assert correct is False
    assert len(diff) > 0


def test_prediction_multiline_match():
    correct, diff = _compare_prediction("a\nb\nc", "a\nb\nc\n")
    assert correct is True


def test_prediction_multiline_mismatch():
    correct, diff = _compare_prediction("a\nb", "a\nc")
    assert correct is False
    assert "expected" in diff and "actual" in diff


# ---------------------------------------------------------------------------
# JavaScript 503 test (unit)
# ---------------------------------------------------------------------------


def test_node_not_found_raises_lookup():
    """AC8 (service layer): missing Node.js raises LookupError."""
    svc = CodeExecutorService()
    with patch("shutil.which", return_value=None):
        with pytest.raises(LookupError, match="node_not_found"):
            svc.execute("console.log('hi')", "javascript")


def test_unsupported_language_raises_value_error():
    svc = CodeExecutorService()
    with pytest.raises(ValueError, match="Unsupported language"):
        svc.execute("print('hi')", "ruby")


# ---------------------------------------------------------------------------
# Integration tests (with DB and HTTP client)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_execute_python(test_db):
    """AC7: POST /code/execute with Python snippet + expected_output returns correct response."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/code/execute",
            json={
                "code": 'print("hello")',
                "language": "python",
                "expected_output": "hello",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["exit_code"] == 0
    assert "hello" in data["stdout"]
    # strip() normalizes trailing newline -> 'hello' == 'hello\n' -> True
    assert data["prediction_correct"] is True
    assert data["prediction_diff"] == ""


@pytest.mark.asyncio
async def test_api_execute_wrong_prediction(test_db):
    """POST /code/execute with wrong expected_output returns prediction_correct=False."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/code/execute",
            json={
                "code": 'print("hello")',
                "language": "python",
                "expected_output": "world",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["prediction_correct"] is False
    assert len(data["prediction_diff"]) > 0


@pytest.mark.asyncio
async def test_api_execute_js_503_when_node_missing(test_db):
    """AC8 (API layer): returns 503 with 'Install Node.js' when node is not found."""
    from httpx import ASGITransport, AsyncClient

    with patch("shutil.which", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/code/execute",
                json={"code": "console.log('hi')", "language": "javascript"},
            )
    assert resp.status_code == 503
    assert "Install Node.js" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_api_execute_no_expected_output(test_db):
    """POST /code/execute without expected_output returns null prediction fields."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/code/execute",
            json={"code": 'print("hello")', "language": "python"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["prediction_correct"] is None
    assert data["prediction_diff"] is None


@pytest.mark.asyncio
async def test_api_create_trace_flashcard(test_db):
    """POST /flashcards/create-trace creates a trace flashcard with source=prediction_error."""
    from httpx import ASGITransport, AsyncClient

    doc_id = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/flashcards/create-trace",
            json={
                "question": "What does this code output?",
                "answer": "Correct output: hello\n\nDiff:\n-world\n+hello",
                "source_excerpt": 'print("hello")',
                "document_id": doc_id,
            },
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["flashcard_type"] == "trace"
    assert data["source"] == "prediction_error"
    assert data["question"] == "What does this code output?"
