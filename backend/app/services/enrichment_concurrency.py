"""Bounds concurrent enrichment LLM calls to what Ollama can actually serve.

Sized from OLLAMA_NUM_PARALLEL: issuing more only moves the wait into Ollama's
queue, where it counts against the caller's request timeout (I-31).
"""

import asyncio
import weakref

from app import config as _config_module

# Keyed by running loop so the cap is shared within the app's loop but isolated
# across per-test event loops (a module-level Semaphore would bind to one loop).
_semaphores: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def enrichment_concurrency() -> int:
    """How many enrichment LLM calls may be in flight at once."""
    try:
        n = int(_config_module.get_settings().OLLAMA_NUM_PARALLEL)
    except (AttributeError, TypeError, ValueError):
        n = 1
    return max(1, n)


def get_enrichment_llm_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _semaphores.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(enrichment_concurrency())
        _semaphores[loop] = sem
    return sem
