"""Bounds concurrent enrichment LLM calls so parallel per-document workers do
not stampede the single local Ollama: each structured-output call can take
~45s+, and N concurrent calls mutually starve and time out."""

import asyncio

_MAX_CONCURRENT_ENRICHMENT_LLM_CALLS = 2

# Keyed by running loop so the cap is shared within the app's loop but isolated
# across per-test event loops (a module-level Semaphore would bind to one loop).
_semaphores: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}


def get_enrichment_llm_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _semaphores.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(_MAX_CONCURRENT_ENRICHMENT_LLM_CALLS)
        _semaphores[loop] = sem
    return sem
