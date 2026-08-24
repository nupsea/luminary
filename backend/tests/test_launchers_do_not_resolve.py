"""A shipped launcher must run what was installed, never re-resolve it.

`uv run` resolves the project before executing, and resolves DEFAULT groups --
here `dev`, `full` and `media`. Every launch therefore reinstalled exactly what
the installer had deliberately left out, including faster-whisper, whose PyAV
wheels carry the GPL binaries the licence carve-out exists to keep out of a
distributed install. It also made a local-first app require the network to
start, and in the Docker image it pulled 46 packages on every container boot.

Developer entry points (`make dev`, luminary.sh, dev-logs.sh) are excluded on
purpose: there, resolving on run is the point.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Launchers a user runs after installing, and the Docker image's entrypoint.
SHIPPED_LAUNCHERS = ("scripts/start.sh", "scripts/install.ps1", "Dockerfile")


def _logical_lines(text: str) -> list[str]:
    """Join shell and PowerShell line continuations.

    PowerShell continues with a trailing backtick, so `Start-Process -FilePath
    "uv"` and the `-ArgumentList "run", "uvicorn", ...` that follows are one
    invocation split across physical lines. Scanning physical lines missed it
    entirely -- this guard passed on install.ps1 while it was still broken.
    """
    joined, buf = [], ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.endswith(("`", "\\")):
            buf += line[:-1] + " "
            continue
        joined.append((buf + line).strip())
        buf = ""
    if buf:
        joined.append(buf.strip())
    return joined


@pytest.mark.parametrize("relpath", SHIPPED_LAUNCHERS)
def test_a_shipped_launcher_never_resolves_dependencies(relpath):
    for line in _logical_lines((REPO / relpath).read_text()):
        if line.startswith("#") or "uvicorn" not in line:
            continue
        if not re.search(r"\buv\b", line):
            continue
        assert "--no-sync" in line or "--frozen" in line, (
            f"{relpath} launches uvicorn through uv without --no-sync: {line}"
        )


def test_the_docker_entrypoint_does_not_go_through_uv_at_all():
    """Nothing to resolve and nothing to shell out to: the image was built with
    exactly the dependencies it should run."""
    cmd = [
        ln for ln in (REPO / "Dockerfile").read_text().splitlines() if ln.startswith("CMD ")
    ]
    assert len(cmd) == 1
    assert "uv" not in cmd[0].split()
