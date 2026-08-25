"""Keep the interactive model resident where a reload is what the user waits for.

Ollama unloads an idle model after `OLLAMA_KEEP_ALIVE` (30m here) and the next
call pays a full load. What that load *costs* is a property of the host, not of
the model. Measured on an Intel i7-8850H in a 12GB Docker VM, `qwen3.5:4b` loads
in anywhere from 9.59s to 155.45s -- 86.25s of it inside one real question, and
159.92s at start-up.

That spread is the point, and it is not a page-cache effect: loads timed back to
back with the cache deliberately dropped and deliberately retained came out
35.5s/21.7s dropped against 48.9s/12.7s retained, which separates nothing. A
load here costs tens of seconds for reasons that do not reduce to one tunable,
so the reliable move is not to pay it. On the Apple Silicon hosts this app was
tuned on the same load is seconds, which is why nothing upstream treats an
eviction as an event worth avoiding. It is one. A reported question that took
261s spent 86 of those seconds loading a model that had been resident an hour
earlier -- and the graph billed that load to the intent classifier:

    [perf] classify_node LLM fallback took 94.10s

The classifier's own work in that call was 189 prompt tokens and 4 generated
ones, 6.6s of it. The other 87.5s was a model load, which is why this was twice
looked for in the classifier and twice not found there.

**The gate is a measurement, never a platform check.** `_warm_llm` already times
the first local generation at start-up; that number is this host's answer, and
it is right for a CPU-only Intel laptop, a Docker VM, and a GPU box alike
without any of them being named. `platform.machine()` would be a guess about the
cause; the probe is a measurement of the effect.

The probe is not purely a load, and does not need to be -- see
`record_startup_probe`. It is what this machine charges for a trivial answer
while it is starting up, which is the thing worth knowing.

**The ping yields to the user.** At one serving slot (I-31) a ping issued while
an Ask is in flight is latency the user pays, so it is skipped under interactive
pressure -- and skipped again when an interactive call has already reset
Ollama's timer, because then it would buy nothing.

Known gap: the decision is taken once, from the start-up measurement. A host
whose Ollama was down at start-up records nothing and is left alone even if the
user repairs it later with the retry button; it is covered on the next launch.
Re-deciding continuously would mean a loop resident on every host, including the
ones this must not touch.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.config import get_settings

logger = logging.getLogger(__name__)

# What this host measured at start-up: seconds for the first local generation.
# None until warm-up records one -- and None is "unmeasured", never "fast", so an
# unmeasured host does not silently get the loop.
_measured_probe_seconds: float | None = None

# A ping only has to be shorter than the model's answer to a real question; it
# exists to reset a timer, not to produce text.
#
# Measured in place on the host above: 8.05s, against a load of 84s that it
# prevents. Not the ~1s the token count suggests -- a single token decodes in
# ~0.2s and the prompt is a handful more, so the rest is per-call overhead
# (routing, LiteLLM, the runtime accepting the request) that no output bound
# reaches. It is the floor for issuing any local call at all, which is why the
# interval is minutes rather than seconds: at 600s this occupies the one slot
# 1.3% of the time, and only when the host was idle enough to be pinged.
_PING_MAX_TOKENS = 1


def record_startup_probe(seconds: float) -> None:
    """Record what the first local generation cost at start-up. Called by warm-up.

    Deliberately NOT called a load measurement, because it often is not one. A
    probe here measured 91.07s with the model already resident and Ollama never
    reloading it -- `/api/ps` showed it loaded throughout and the log has no
    `starting llama-server` -- so those 91 seconds were a 25-token generation
    losing 8 vCPUs to the embedder, GLiNER and the reranker all constructing at
    once. Other probes on the same host, having actually paid a load, measured
    84.03s and 107.47s.

    That the two are indistinguishable from here is the reason to keep both.
    What the gate needs to know is whether getting a trivial answer out of the
    local model is expensive on this machine, and this number answers that
    whether the cost came from a load, from contention, or from both. Filtering
    out the samples with no load in them was tried and would have thrown away a
    valid 91.07s reading and switched the protection off.
    """
    global _measured_probe_seconds
    _measured_probe_seconds = seconds


def measured_probe_seconds() -> float | None:
    return _measured_probe_seconds


def reset_measurement() -> None:
    """Forget the measurement. For tests, and for nothing else."""
    global _measured_probe_seconds
    _measured_probe_seconds = None


def local_inference_is_slow() -> bool:
    """Whether local inference on this host is slow enough to change behaviour for.

    The host fact other features read, not only this one: an evicted model is
    the user's problem here, and so is a prompt that takes a minute to prefill.

    Unmeasured is not slow: with no measurement this returns False and nothing
    changes, so a host we know nothing about keeps the shipped defaults.
    """
    settings = get_settings()
    if not settings.LLM_KEEP_WARM_ENABLED:
        return False
    if _measured_probe_seconds is None:
        return False
    return _measured_probe_seconds >= settings.LLM_KEEP_WARM_ABOVE_SECONDS


async def _ping_if_idle() -> bool:
    """Reset Ollama's residency timer, unless doing so would cost the user.

    Returns whether a ping was actually issued.
    """
    from app.services.llm_admission import (  # noqa: PLC0415
        current_state,
        under_interactive_pressure,
    )

    if under_interactive_pressure():
        return False

    interval = get_settings().LLM_KEEP_WARM_INTERVAL_SECONDS
    state = current_state()
    if state is not None and state.last_interactive_end > 0.0:
        # A real call inside the last interval already did this for us. Ollama's
        # timer is reset by any generation, not only by ours.
        if (time.monotonic() - state.last_interactive_end) < interval:
            return False

    from app.services.llm import get_llm_service  # noqa: PLC0415

    # Interactive, and not `background=True`. Background resolves the background
    # role's model, which may not be the chat model -- at one resident model
    # (OLLAMA_MAX_LOADED_MODELS=1) pinging it would evict the very model this
    # exists to keep loaded. The cost of being interactive is that background
    # work yields for the ping plus the grace window, which is a fraction of a
    # second on a system that was idle enough for the ping to be issued at all.
    t0 = time.perf_counter()
    await get_llm_service().generate(
        "ping",
        max_tokens=_PING_MAX_TOKENS,
        timeout=get_settings().LLM_WARMUP_TIMEOUT_SECONDS,
    )
    logger.debug("keep-warm ping in %.2fs", time.perf_counter() - t0)
    return True


async def keep_warm_loop() -> None:
    """Hold the interactive model resident. Returns immediately on a fast host."""
    settings = get_settings()
    if not local_inference_is_slow():
        logger.info(
            "Keep-warm off: the first local generation took %s at start-up "
            "(threshold %.0fs)",
            "unmeasured"
            if _measured_probe_seconds is None
            else f"{_measured_probe_seconds:.1f}s",
            settings.LLM_KEEP_WARM_ABOVE_SECONDS,
        )
        return

    interval = settings.LLM_KEEP_WARM_INTERVAL_SECONDS
    logger.info(
        "Keep-warm on: the first local generation took %.1fs at start-up here, so "
        "the model is pinged every %.0fs rather than reloaded after an idle spell",
        _measured_probe_seconds,
        interval,
    )
    while True:
        await asyncio.sleep(interval)
        try:
            await _ping_if_idle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- a failed ping must not end the loop
            # Fails soft and stays quiet: Ollama being down is already reported
            # by the connectivity check, and one line every interval would bury
            # it in the log a bug report is read from.
            logger.debug("keep-warm ping failed: %s", exc)
