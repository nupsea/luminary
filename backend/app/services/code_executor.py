"""Sandboxed code execution service for the Predict-then-Run feature.

Security model:
- subprocess.run with shell=False prevents shell injection via command arguments.
  Code supplied by the user runs inside the subprocess (os.system, etc. still work).
- env={} (empty dict) strips all inherited environment variables.
  sys.executable / shutil.which() resolve absolute paths so PATH is not needed.
- preexec_fn sets RLIMIT_AS (256 MB virtual memory) and RLIMIT_CPU (10 s CPU time)
  on POSIX. On Windows preexec_fn is skipped — resource limits are not enforced.
- timeout=N enforces a wall-clock deadline regardless of CPU time (handles I/O-
  bound infinite loops that RLIMIT_CPU alone would not catch).
- Execution runs in a fresh tempfile.TemporaryDirectory() that is deleted afterward.

Memory limit note: RLIMIT_AS on macOS limits virtual memory but not resident set,
so macOS may not always terminate x=[0]*10**9 with exit_code!=0. The test accepts
either exit_code!=0 or 'MemoryError' in stderr to handle both Linux and macOS.

Kill button note: aborting the frontend fetch only cancels the HTTP request on the
client side. The server subprocess continues until its timeout fires. No cross-process
kill signal is sent on abort.
"""
import difflib
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from functools import lru_cache

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10
_MEMORY_LIMIT_BYTES = 256 * 1024 * 1024  # 256 MB


def _set_resource_limits() -> None:
    """Set RLIMIT_AS and RLIMIT_CPU for the child subprocess. POSIX only."""
    try:
        import resource  # not available on Windows

        resource.setrlimit(
            resource.RLIMIT_AS, (_MEMORY_LIMIT_BYTES, _MEMORY_LIMIT_BYTES)
        )
        resource.setrlimit(
            resource.RLIMIT_CPU, (_TIMEOUT_SECONDS, _TIMEOUT_SECONDS)
        )
    except (AttributeError, ImportError, ValueError):
        pass  # Windows or unsupported platform


class ExecutionResult:
    """Pure data class — no I/O."""

    def __init__(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        elapsed_ms: int,
        prediction_correct: bool | None,
        prediction_diff: str | None,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.elapsed_ms = elapsed_ms
        self.prediction_correct = prediction_correct
        self.prediction_diff = prediction_diff


def _compare_prediction(expected: str, actual: str) -> tuple[bool, str]:
    """Pure function. Compares stripped expected vs stripped actual.

    Trailing newlines are normalized by strip() so 'hello' == 'hello\\n'.
    Returns (correct: bool, diff: str).

    Edge case: expected='hello', actual='hello\\n' -> correct=True
    because both strip() to 'hello'. This behavior is documented and intentional.
    """
    exp_stripped = expected.strip()
    act_stripped = actual.strip()
    correct = exp_stripped == act_stripped
    diff_lines = list(
        difflib.unified_diff(
            exp_stripped.splitlines(keepends=True),
            act_stripped.splitlines(keepends=True),
            fromfile="expected",
            tofile="actual",
        )
    )
    diff = "".join(diff_lines) if not correct else ""
    return correct, diff


class CodeExecutorService:
    """Execute code snippets in an isolated subprocess."""

    def execute(
        self,
        code: str,
        language: str,
        timeout_ms: int = 10_000,
        expected_output: str | None = None,
    ) -> ExecutionResult:
        """Execute code in a sandboxed subprocess.

        Python: uses sys.executable (the uv-managed venv Python).
        JavaScript: uses shutil.which('node'); raises LookupError if absent.
        Raises ValueError for unsupported languages.
        Raises LookupError with message 'node_not_found' when Node.js is not installed.
        """
        language = language.lower()
        if language == "python":
            cmd = [sys.executable, "-c", code]
            preexec: object = _set_resource_limits
        elif language in ("javascript", "js"):
            node_path = shutil.which("node")
            if node_path is None:
                raise LookupError("node_not_found")
            cmd = [node_path, "-e", code]
            preexec = _set_resource_limits
        else:
            raise ValueError(f"Unsupported language: {language!r}")

        timeout_s = min(timeout_ms / 1000.0, _TIMEOUT_SECONDS)

        # preexec_fn is POSIX-only; skip on Windows
        extra: dict = {} if sys.platform == "win32" else {"preexec_fn": preexec}

        with tempfile.TemporaryDirectory() as tmp_dir:
            start = time.monotonic()
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=timeout_s,
                    shell=False,
                    cwd=tmp_dir,
                    env={},
                    text=True,
                    check=False,
                    **extra,
                )
                elapsed_ms = int((time.monotonic() - start) * 1000)
                stdout = proc.stdout
                stderr = proc.stderr
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                elapsed_ms = int(timeout_s * 1000)
                stdout = ""
                stderr = f"Timeout after {timeout_s:.0f}s"
                exit_code = 124  # conventional timeout exit code

        prediction_correct: bool | None = None
        prediction_diff: str | None = None
        if expected_output is not None:
            prediction_correct, prediction_diff = _compare_prediction(
                expected_output, stdout
            )

        logger.info(
            "code_execute: language=%s exit_code=%d elapsed_ms=%d",
            language,
            exit_code,
            elapsed_ms,
        )
        return ExecutionResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            elapsed_ms=elapsed_ms,
            prediction_correct=prediction_correct,
            prediction_diff=prediction_diff,
        )


@lru_cache
def get_code_executor_service() -> CodeExecutorService:
    return CodeExecutorService()
