"""Run an installed connector for one request, as its own process (`docs/roadmap.md` §7).

The connector speaks `luminary_source_sdk.protocol`: one request line on stdin, event lines on
stdout. It gets credentials only in that request, and an environment cut down to what a
network fetch needs, so nothing else the backend holds reaches it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.exceptions import LuminaryError

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
# A whole book through a slow proxy; a fetch that outlasts this is stuck, not slow.
FETCH_TIMEOUT_S = 60 * 60
QUICK_TIMEOUT_S = 120  # describe and preview
_LINE_LIMIT = 1024 * 1024
_TERM_GRACE_S = 3.0
# What a fetch needs from the environment: the binary path, a home and temp directory, the
# locale, and the proxy and CA settings `proxy_env` pinned. Never the backend's own keys.
_ENV_KEYS = (
    "PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
)  # fmt: skip

Progress = Callable[[float, str], None]


@dataclass(frozen=True)
class InstalledConnector:
    name: str
    python: str
    entry: str
    description: dict[str, Any]


class ConnectorFailed(LuminaryError):
    """The connector answered with an error, or died before answering."""

    status_code = 502

    def __init__(self, detail: str, code: str = "internal") -> None:
        super().__init__(detail, code=code)
        self.code = code


class ConnectorTimeout(ConnectorFailed):
    status_code = 504


_fetch_slots: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}


def _fetch_slot() -> asyncio.Semaphore:
    """One fetch at a time: each is a long download, and two compete for one connection."""
    return _fetch_slots.setdefault(asyncio.get_running_loop(), asyncio.Semaphore(1))


def child_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in _ENV_KEYS if k in os.environ}
    return env | {"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}


async def call(
    connector: InstalledConnector,
    op: str,
    *,
    input: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
    dest: str | None = None,
    on_progress: Progress | None = None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """The connector's `result` data for one request. Raises `ConnectorFailed`."""
    request = {
        "protocol": PROTOCOL_VERSION,
        "op": op,
        "input": input or {},
        "credentials": credentials or {},
        "dest": dest,
    }
    timeout = timeout_s or (FETCH_TIMEOUT_S if op == "fetch" else QUICK_TIMEOUT_S)
    if op != "fetch":
        return await _run(connector, request, on_progress, timeout)
    async with _fetch_slot():
        return await _run(connector, request, on_progress, timeout)


async def _run(
    connector: InstalledConnector,
    request: dict[str, Any],
    on_progress: Progress | None,
    timeout: float,
) -> dict[str, Any]:
    # A process group of its own, so a timeout or cancel stops whatever it started too.
    group = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if sys.platform == "win32"
        else {"start_new_session": True}
    )
    proc = await asyncio.create_subprocess_exec(
        connector.python,
        "-I",
        "-m",
        "luminary_source_sdk.serve",
        connector.entry,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=child_env(),
        cwd=tempfile.gettempdir(),
        limit=_LINE_LIMIT,
        **group,
    )
    stderr_tail: deque[str] = deque(maxlen=20)
    stderr_task = asyncio.ensure_future(_drain_stderr(proc, connector.name, stderr_tail))
    try:
        async with asyncio.timeout(timeout):
            proc.stdin.write((json.dumps(request) + "\n").encode())
            await proc.stdin.drain()
            proc.stdin.close()
            return await _events(proc, connector.name, on_progress, stderr_tail)
    except TimeoutError as exc:
        raise ConnectorTimeout(f"{connector.name} did not answer within {timeout:.0f}s") from exc
    finally:
        await _stop(proc)
        stderr_task.cancel()


async def _events(proc, name: str, on_progress: Progress | None, stderr_tail) -> dict[str, Any]:
    async for raw in proc.stdout:
        try:
            event = json.loads(raw)
        except ValueError:
            logger.warning("connector %s wrote a non-protocol line", name)
            continue
        if isinstance(event, dict) and (data := _on_event(event, name, on_progress)) is not None:
            return data
    code = await proc.wait()
    last = f": {stderr_tail[-1]}" if stderr_tail else ""
    raise ConnectorFailed(f"{name} exited with code {code} before answering{last}")


def _on_event(event: dict, name: str, on_progress: Progress | None) -> dict[str, Any] | None:
    """The result's data once the connector answers; None for an event on the way there."""
    kind = event.get("event")
    if kind == "result":
        return dict(event.get("data") or {})
    if kind == "error":
        raise ConnectorFailed(str(event.get("message") or "failed"), str(event.get("code")))
    if kind == "progress" and on_progress is not None:
        on_progress(float(event.get("fraction") or 0.0), str(event.get("stage") or ""))
    elif kind == "log":
        _log_event(event, name)
    return None


def _log_event(event: dict, name: str) -> None:
    level = logging.getLevelName(str(event.get("level", "info")).upper())
    logger.log(level if isinstance(level, int) else logging.INFO, "[%s] %s", name,
               event.get("message", ""))  # fmt: skip


async def _drain_stderr(proc, name: str, tail: deque[str]) -> None:
    async for raw in proc.stderr:
        line = raw.decode("utf-8", "replace").rstrip()
        if line:
            tail.append(line[:300])
            logger.info("[%s] %s", name, line[:2000])


async def _stop(proc) -> None:
    """SIGTERM to the connector's process group, then SIGKILL after a grace period."""
    if proc.returncode is not None:
        return
    _signal_group(proc, signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), _TERM_GRACE_S)
    except TimeoutError:
        _signal_group(proc, signal.SIGKILL if sys.platform != "win32" else signal.SIGTERM)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), _TERM_GRACE_S)


def _signal_group(proc, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        if sys.platform == "win32":
            # taskkill /T reaches the children a connector started; terminate alone does not.
            taskkill = (
                Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
            )
            subprocess.run(  # noqa: S603 -- fixed argv, our own child's pid
                [str(taskkill), "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(proc.pid, sig)
