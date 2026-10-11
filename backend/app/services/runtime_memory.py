"""Keep a local Ollama's prompt cache from taking the machine (I-64).

Every Ollama Luminary starts caps llama-server's prompt cache, but a source or dev run
adopts whatever Ollama is listening, and on macOS `launchctl setenv` does not outlive a
reboot: Ollama.app then starts from the login items with llama.cpp's 8 GiB default.
qwen3.5 never reuses an entry, so each background prompt adds about 200 MB.

Two answers. The host banner reads the server's cap on every fetch and names the fix for
the way that server was started. And the background gate trims a runner whose resident
memory exceeds what Ollama reports for its loaded models: unloading the model drops the
cache, the next call reloads it. That is a leak detector, not a residency figure, so it
does not contradict I-39.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import httpx
import psutil

from app.config import get_settings

logger = logging.getLogger(__name__)

# Excess = runner RSS minus `/api/ps` sizes. A runner capped at 512 MiB peaked at 1.60 GB
# over 40 calls with vision; uncapped it passed 3 GB at call 13 and reached 8.2 GB by 40.
EXCESS_LIMIT_BYTES = 3 * 1024**3
_CHECK_EVERY_SECONDS = 15.0
# supervisor.rs clamps the cap to this; anything above it is not a bound we chose.
_MAX_BOUNDED_MIB = 2048
_LLAMA_DEFAULT_MIB = 8192
_CAP_VAR = "LLAMA_ARG_CACHE_RAM"
_RUNNER = "llama-server"

# Each launch has its own fix: `launchctl setenv` reaches Ollama.app and launchd jobs
# only, a terminal's server reads its shell, a systemd server reads its unit.
Launch = Literal["macos_app", "launchd", "systemd", "windows", "terminal"]

_last_check = 0.0
# The server whose runner outgrew the bound; a restarted server is judged afresh.
_ballooned_pid: int | None = None


@dataclass(frozen=True)
class PromptCacheStatus:
    unbounded: bool
    launch: Launch
    # The launchd label or systemd unit that restarts the server, where there is one.
    service: str | None = None


def _local_port() -> int | None:
    parsed = urlparse(get_settings().OLLAMA_URL)
    host = parsed.hostname or ""
    try:
        local = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = False
    return (parsed.port or 11434) if local else None


def _listens(proc: psutil.Process, port: int) -> bool:
    return any(
        c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN
        for c in proc.net_connections(kind="inet")
    )


def _server(port: int) -> psutil.Process | None:
    """The Ollama listening on `port`, or None when that is unknowable."""
    hidden = []
    for proc in psutil.process_iter(["name", "cmdline"]):
        if "ollama" not in (proc.info["name"] or "").lower():
            continue
        try:
            if _listens(proc, port):
                return proc
        except psutil.AccessDenied:
            # Another user's server (Linux's systemd unit runs as `ollama`) hides its sockets.
            if "serve" in (proc.info["cmdline"] or []):
                hidden.append(proc)
        except psutil.NoSuchProcess:
            continue
    return hidden[0] if len(hidden) == 1 else None


def _runners(server: psutil.Process) -> list[psutil.Process]:
    return [c for c in server.children(recursive=True) if c.name() == _RUNNER]


def _env_cap(env: dict[str, str]) -> int:
    value = env.get(_CAP_VAR)
    return _LLAMA_DEFAULT_MIB if value is None else int(value)


def cache_cap_mib(runner: psutil.Process) -> int | None:
    """The runner's prompt-cache cap in MiB: llama.cpp's 8192 when unset, None if unreadable."""
    args = runner.cmdline()
    for flag in ("--cache-ram", "-cram"):
        if flag in args[:-1]:
            return int(args[args.index(flag) + 1])
    try:
        return _env_cap(runner.environ())
    except (psutil.AccessDenied, OSError):
        return None


def _bounded(cap: int) -> bool:
    return 0 <= cap <= _MAX_BOUNDED_MIB


def _unit_of(cgroup: str) -> str | None:
    """The system unit in a `/proc/<pid>/cgroup` line; a login session or a user's own
    units are not one."""
    leaf = cgroup.strip().rsplit("/", 1)[-1]
    return leaf if leaf.endswith(".service") and not leaf.startswith("user@") else None


def _systemd_unit(pid: int) -> str | None:
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            return _unit_of(f.read())
    except OSError:
        return None


def _systemd_env(unit: str) -> dict[str, str] | None:
    """A system unit's environment, readable without the root its process would need."""
    try:
        out = subprocess.run(  # noqa: S603 -- fixed argv
            ["systemctl", "show", unit, "-p", "Environment", "-p", "EnvironmentFiles"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    env = dict(item.split("=", 1) for item in shlex.split(props.get("Environment", "")))
    # A file can set the cap where `show` cannot see it.
    if _CAP_VAR not in env and props.get("EnvironmentFiles"):
        return None
    return env


def _launch(server: psutil.Process) -> tuple[Launch, str | None]:
    if sys.platform == "win32":
        return "windows", None
    if sys.platform == "darwin":
        with contextlib.suppress(psutil.AccessDenied, OSError):
            if ".app/Contents/" in server.exe():
                return "macos_app", None
        with contextlib.suppress(psutil.AccessDenied, OSError):
            # launchd names a job's process by its label; a terminal's is "0", an app's
            # "application.<bundle id>".
            label = server.environ().get("XPC_SERVICE_NAME", "0")
            if label != "0" and not label.startswith("application."):
                return "launchd", label
        return "terminal", None
    unit = _systemd_unit(server.pid)
    return ("systemd", unit) if unit else ("terminal", None)


def _server_cap(server: psutil.Process, systemd_unit: str | None) -> int | None:
    """The live runners' cap, else the one the server hands its next runner."""
    caps = []
    for runner in _runners(server):
        try:
            caps.append(cache_cap_mib(runner))
        except (psutil.NoSuchProcess, ValueError):
            caps.append(None)
    if caps and None not in caps:
        return max(caps)
    try:
        env = server.environ()
    except (psutil.AccessDenied, OSError):
        env = _systemd_env(systemd_unit) if systemd_unit else None
    try:
        return None if env is None else _env_cap(env)
    except ValueError:
        return None


def _inspect(port: int) -> PromptCacheStatus | None:
    server = _server(port)
    if server is None:
        return None
    try:
        launch, service = _launch(server)
        cap = _server_cap(server, service if launch == "systemd" else None)
    except psutil.NoSuchProcess:
        return None
    if server.pid == _ballooned_pid:
        return PromptCacheStatus(True, launch, service)
    if cap is None:
        return None
    return PromptCacheStatus(not _bounded(cap), launch, service)


async def prompt_cache_status() -> PromptCacheStatus | None:
    """The local server's cap as it stands now; None when unknowable. Never raises."""
    port = _local_port()
    if port is None:
        return None
    try:
        return await asyncio.to_thread(_inspect, port)
    except psutil.Error as exc:
        logger.info("prompt-cache cap unreadable: %s", exc)
        return None


async def log_prompt_cache_status() -> None:
    status = await prompt_cache_status()
    if status and status.unbounded:
        logger.warning(
            "The local model server (started as: %s) keeps up to 8 GB of old prompts in "
            "memory. Set LLAMA_ARG_CACHE_RAM=512 where it starts and restart it; the host "
            "banner names the steps (I-64).",
            status.launch,
        )


def _resident_bytes(port: int) -> tuple[int | None, int]:
    server = _server(port)
    if server is None:
        return None, 0
    total = 0
    for runner in _runners(server):
        # A runner exits when its model unloads, between listing it and reading it.
        with contextlib.suppress(psutil.NoSuchProcess):
            total += runner.memory_info().rss
    return server.pid, total


async def _ollama(path: str, payload: dict | None = None) -> dict:
    url = f"{get_settings().OLLAMA_URL}{path}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await (client.post(url, json=payload) if payload else client.get(url))
        resp.raise_for_status()
        return resp.json()


async def trim_if_ballooned() -> bool:
    """Unload the local models when their runner holds far more than they weigh.

    Called by the background gate while it holds the slot with nothing else in flight,
    so no call loses its runner. Throttled: one process scan per `_CHECK_EVERY_SECONDS`.
    Never raises; a failed check leaves the runner as it was.
    """
    global _last_check, _ballooned_pid
    now = time.monotonic()
    if now - _last_check < _CHECK_EVERY_SECONDS:
        return False
    _last_check = now
    port = _local_port()
    if port is None:
        return False
    try:
        pid, resident = await asyncio.to_thread(_resident_bytes, port)
        if not resident:
            return False
        loaded = (await _ollama("/api/ps")).get("models") or []
        excess = resident - sum(int(m.get("size") or 0) for m in loaded)
        if excess < EXCESS_LIMIT_BYTES:
            return False
        _ballooned_pid = pid
        for model in loaded:
            await _ollama("/api/generate", {"model": model.get("name"), "keep_alive": 0})
    except (httpx.HTTPError, ValueError, psutil.Error) as exc:
        logger.info("prompt-cache check skipped: %s", exc)
        return False
    logger.warning(
        "Unloaded the local model: its server held %.1f GB beyond the model, the prompt cache "
        "has no bound (I-64). The next call reloads it.",
        excess / 1e9,
    )
    return True
