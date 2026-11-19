"""#211/#476: a timed-out test is named in the output its worker leaves behind."""

import subprocess
import sys
from pathlib import Path


def test_a_timed_out_test_names_itself_on_stderr(tmp_path):
    (tmp_path / "test_slow.py").write_text(
        "import time\n\ndef test_ingest():\n    time.sleep(10)\n"
    )
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(tmp_path),
            "-p",
            "timeout_notice",
            "-p",
            "no:cacheprovider",
            "-o",
            "timeout=2",
            "-o",
            "timeout_method=thread",
            "-o",
            "addopts=",
            "-q",
        ],
        cwd=tmp_path,
        env={**_env(), "PYTHONPATH": str(Path(__file__).parent)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 1
    assert "test_slow.py::test_ingest reached its 2s timeout" in run.stderr
    assert "time.sleep" in run.stderr or "test_ingest" in run.stderr.split("timeout", 1)[1]


def _env() -> dict[str, str]:
    import os

    return {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
