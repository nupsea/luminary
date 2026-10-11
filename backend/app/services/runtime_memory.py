"""Keep a local Ollama's prompt cache from taking the machine (I-64).

Every Ollama Luminary starts caps llama-server's prompt cache, but a source or dev run
adopts whatever Ollama is listening, and on macOS `launchctl setenv` does not outlive a
reboot: Ollama.app then starts from the login items with llama.cpp's 8 GiB default.
qwen3.5 never reuses an entry, so each background prompt adds about 200 MB.

Two answers. Warmup reads the runner's cap and the host banner names the fix. And the
background gate trims a runner whose resident memory exceeds what Ollama reports for its
loaded models: unloading the model drops the cache, the next call reloads it. That is a
leak detector, not a residency figure, so it does not contradict I-39.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import time
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
_RUNNER = "llama-server"

_last_check = 0.0
_unbounded = False


def prompt_cache_unbounded() -> bool:
    """Whether the local runner was seen without a prompt-cache bound, by its config or its size."""
    return _unbounded


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


def _runners(port: int) -> list[psutil.Process]:
    """llama-server children of the Ollama listening on `port`; empty when that is unknowable."""
    for proc in psutil.process_iter(["name"]):
        if "ollama" not in (proc.info["name"] or "").lower():
            continue
        try:
            if _listens(proc, port):
                return [c for c in proc.children(recursive=True) if c.name() == _RUNNER]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return []


def cache_cap_mib(runner: psutil.Process) -> int | None:
    """The runner's prompt-cache cap in MiB: llama.cpp's 8192 when unset, None if unreadable."""
    args = runner.cmdline()
    for flag in ("--cache-ram", "-cram"):
        if flag in args[:-1]:
            return int(args[args.index(flag) + 1])
    try:
        value = runner.environ().get("LLAMA_ARG_CACHE_RAM")
    except (psutil.AccessDenied, OSError):
        return None
    return 8192 if value is None else int(value)


def _bounded(cap: int | None) -> bool | None:
    if cap is None:
        return None
    return 0 <= cap <= _MAX_BOUNDED_MIB


def _read_caps(port: int) -> list[int | None]:
    caps = []
    for runner in _runners(port):
        try:
            caps.append(cache_cap_mib(runner))
        except (psutil.NoSuchProcess, ValueError):
            caps.append(None)
    return caps


async def check_prompt_cache_cap() -> bool | None:
    """Read the loaded runner's cap: True is bounded, None unknowable. Never raises."""
    global _unbounded
    port = _local_port()
    if port is None:
        return None
    try:
        verdicts = [_bounded(c) for c in await asyncio.to_thread(_read_caps, port)]
    except psutil.Error as exc:
        logger.info("prompt-cache cap unreadable: %s", exc)
        return None
    if False in verdicts:
        _unbounded = True
        logger.warning(
            "The local model server keeps up to 8 GB of old prompts in memory. Quit Ollama, run "
            "`launchctl setenv LLAMA_ARG_CACHE_RAM 512` (macOS) or set LLAMA_ARG_CACHE_RAM=512 "
            "in its environment, then start it again (I-64)."
        )
        return False
    return True if verdicts and all(verdicts) else None


def _resident_bytes(port: int) -> int:
    total = 0
    for runner in _runners(port):
        # A runner exits when its model unloads, between listing it and reading it.
        with contextlib.suppress(psutil.NoSuchProcess):
            total += runner.memory_info().rss
    return total


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
    global _last_check, _unbounded
    now = time.monotonic()
    if now - _last_check < _CHECK_EVERY_SECONDS:
        return False
    _last_check = now
    port = _local_port()
    if port is None:
        return False
    try:
        resident = await asyncio.to_thread(_resident_bytes, port)
        if not resident:
            return False
        loaded = (await _ollama("/api/ps")).get("models") or []
        excess = resident - sum(int(m.get("size") or 0) for m in loaded)
        if excess < EXCESS_LIMIT_BYTES:
            return False
        _unbounded = True
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
