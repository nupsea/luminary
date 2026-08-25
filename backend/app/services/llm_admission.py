"""Priority gate in front of the local runtime's serving slots.

Residency (P1) is a memory control with no latency term in it. Capping loaded
models does nothing for an Ask that arrives while ingestion holds the only slot:
measured on a 36GB host, interactive TTFT under ingest load was 75-115s against
0.56s idle. Left alone, that trades a crash for a stall.

Ollama exposes no preemption primitive, so the finest yield granularity is one
completed call (I-31). A background call therefore checks interactive pressure
before issuing its *next* call and waits for the pressure to clear; interactive
work never waits here, it goes straight to the runtime.

Three properties are load-bearing:

- **The reserve comes from the serving width, not from a new knob.** At one slot
  there is no slot to give, so background suspends outright; at two or more, one
  slot stays free for interactive work and the rest keep serving ingestion.
- **The grace window keeps a multi-turn chat ahead of the queue.** Without it a
  background call is admitted between a user's turns and the next question waits
  behind it.
- **Deferral is bounded, and pressure expires.** A user who chats continuously
  must not stop ingestion for ever, so a call waiting longer than the bound is
  admitted anyway and counted as a forced admission; separately, an interactive
  call still in flight after ten minutes is presumed leaked and stops counting.
  Nothing here can wedge permanently, which matters because a deferring
  background call may be holding a lock an interactive request needs.

Only local models are gated. A cloud call contends for nothing on this machine,
and holding one back would make hybrid mode slower for no reason.
"""

import asyncio
import contextlib
import logging
import time
import weakref
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from app import config as _config_module
from app.services.connectivity import is_cloud_model
from app.services.enrichment_concurrency import enrichment_concurrency

logger = logging.getLogger(__name__)

_POLL_SECONDS = 0.2

# How long an interactive call keeps applying pressure with no sign of life.
#
# Pressure decays from the call's **last activity**, not from when it started: a
# stream bumps this on every token, so a live answer keeps yielding to the user
# however long it runs, while one the client walked away from stops counting
# shortly after its last token.
#
# That distinction is load-bearing rather than tidy. Holding the gate for the
# lifetime of an async generator means the release depends on that generator
# being closed, and a consumer that breaks out of the loop -- a browser
# navigating away mid-answer, a probe that stops at the first token -- may never
# close it. Measured: one abandoned stream left `interactive_inflight` stuck at
# 1, which suspends every background call behind it.
#
# Sized above the worst first-token latency measured under ingest load (88s) so
# a genuinely slow answer is never mistaken for an abandoned one, and far below
# the old 600s, which stalled ingestion for ten minutes per abandoned stream.
_STALE_INTERACTIVE_SECONDS = 180.0

# Absolute ceiling on how long background work may be deferred.
#
# Not `_STALE_INTERACTIVE_SECONDS`: that is "no token for three minutes", a
# liveness test, and a healthy answer streaming for six minutes never trips it.
# Reusing it as the deferral ceiling force-admitted background work into the
# middle of a live answer, which is the case this bound exists to prevent.
#
# Ten minutes is where an answer is pathological rather than slow and ingestion
# should get the runtime back regardless. Nothing depends on this for safety --
# pressure decay already stops the gate wedging; this only decides how long
# ingestion yields to a user who is actually being served.
_MAX_DEFER_CEILING_SECONDS = 600.0


@dataclass
class AdmissionState:
    """Live counters for one event loop. Also the source of the UI's paused state."""

    # One entry per in-flight interactive call, holding its last-activity time.
    # A list of single-element lists so a streaming call can bump its own entry
    # in place without needing an index that reordering would invalidate.
    interactive_activity: list[list[float]] = field(default_factory=list)
    background_inflight: int = 0
    background_waiting: int = 0
    last_interactive_end: float = 0.0
    # How long the most recent interactive call ran. The deferral bound is
    # wall-clock, and 60s was calibrated where a call takes seconds; on a CPU-only
    # host one runs into minutes, so the bound expired mid-answer and admitted
    # background work into a one-slot runtime AHEAD of the user's own call.
    # Measured on such a host: 45s of prompt eval inside a 280s wait for first
    # token.
    last_interactive_seconds: float = 0.0
    deferred_calls: int = 0
    deferred_seconds: float = 0.0
    forced_admissions: int = 0

    @property
    def interactive_inflight(self) -> int:
        return len(self.interactive_activity)


# Keyed by running loop, as in enrichment_concurrency: state shared within the
# app's single loop, isolated across per-test event loops.
_states: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, AdmissionState] = (
    weakref.WeakKeyDictionary()
)


def _state() -> AdmissionState:
    loop = asyncio.get_running_loop()
    state = _states.get(loop)
    if state is None:
        state = AdmissionState()
        _states[loop] = state
    return state


def current_state() -> AdmissionState | None:
    """State for the running loop, or None when called outside one."""
    try:
        return _state()
    except RuntimeError:
        return None


def _settings():
    return _config_module.get_settings()


def admission_enabled() -> bool:
    return bool(_settings().LLM_ADMISSION_ENABLED)


def background_reserve() -> int:
    """How many background calls may stay in flight while interactive work is live.

    One slot is held back for interactive work; at a single slot that leaves
    zero, which is the hard suspend a low-memory host needs.
    """
    return max(0, enrichment_concurrency() - 1)


def _max_defer_seconds(state: AdmissionState | None = None) -> float:
    """The configured bound, or the last interactive call's duration if longer.

    Deferring background work for 60s means "wait out the answer" only where an
    answer takes less than 60s. Where one takes six minutes the bound expires
    while the user is still waiting, and the forced admission queues background
    work ahead of them -- the opposite of what the guard is for.

    Still bounded, and never past the staleness window, so the starvation guard
    this exists for keeps working: a user chatting continuously cannot hold
    ingestion off for ever, and nothing here can wedge.
    """
    configured = float(_settings().LLM_ADMISSION_MAX_DEFER_SECONDS)
    if state is None:
        return configured
    return min(max(configured, state.last_interactive_seconds), _MAX_DEFER_CEILING_SECONDS)


def under_interactive_pressure() -> bool:
    """Whether an interactive call is in flight or finished within the grace window.

    A call with no activity for longer than `_STALE_INTERACTIVE_SECONDS` stops
    counting. A stream bumps its own activity per token, so this separates a slow
    answer from one the client walked away from -- which a start-time-only rule
    could not, and which leaked in practice.
    """
    state = current_state()
    if state is None:
        return False
    now = time.monotonic()
    if any(now - seen[0] < _STALE_INTERACTIVE_SECONDS for seen in state.interactive_activity):
        return True
    if state.last_interactive_end <= 0.0:
        return False
    grace = float(_settings().LLM_ADMISSION_GRACE_SECONDS)
    return (now - state.last_interactive_end) < grace


def paused_for_interaction() -> bool:
    """Whether background LLM work is being held back right now.

    This is the honest signal behind the UI's "paused while you're asking" state
    (I-10): it is true only when a background call is actually waiting, not
    merely when a question is in flight.
    """
    state = current_state()
    return state is not None and state.background_waiting > 0


def admission_stats() -> dict[str, float | int | bool]:
    state = current_state()
    if state is None:
        return {}
    return {
        "enabled": admission_enabled(),
        "reserve": background_reserve(),
        "interactive_inflight": state.interactive_inflight,
        "background_inflight": state.background_inflight,
        "background_waiting": state.background_waiting,
        "deferred_calls": state.deferred_calls,
        "deferred_seconds": round(state.deferred_seconds, 3),
        "forced_admissions": state.forced_admissions,
    }


def _blocked(state: AdmissionState, reserve: int) -> bool:
    return state.background_inflight >= reserve and under_interactive_pressure()


async def _wait_for_slot(state: AdmissionState) -> None:
    reserve = background_reserve()
    if not _blocked(state, reserve):
        return

    max_defer = _max_defer_seconds(state)
    started = time.monotonic()
    state.background_waiting += 1
    state.deferred_calls += 1
    try:
        while _blocked(state, reserve):
            waited = time.monotonic() - started
            if waited >= max_defer:
                state.forced_admissions += 1
                logger.warning(
                    "background LLM call admitted after %.1fs of interactive pressure; "
                    "ingestion would otherwise stall",
                    waited,
                )
                break
            await asyncio.sleep(min(_POLL_SECONDS, max_defer - waited))
    finally:
        state.background_waiting -= 1
        state.deferred_seconds += time.monotonic() - started


@asynccontextmanager
async def interactive_call():
    """Mark interactive pressure for the life of a call, plus the grace window."""
    state = _state()
    started = time.monotonic()
    entry = [started]
    state.interactive_activity.append(entry)
    try:
        yield entry
    finally:
        with contextlib.suppress(ValueError):
            state.interactive_activity.remove(entry)
        now = time.monotonic()
        state.last_interactive_end = now
        state.last_interactive_seconds = now - started


@asynccontextmanager
async def background_call():
    """Hold a background call until the runtime has room for it."""
    state = _state()
    if admission_enabled():
        await _wait_for_slot(state)
    state.background_inflight += 1
    try:
        yield
    finally:
        state.background_inflight -= 1


@asynccontextmanager
async def admit(model: str, *, background: bool):
    """The one gate `LLMService` applies. Cloud models pass straight through.

    Yields a `keepalive` callable. A streaming caller must invoke it as tokens
    arrive: that is what tells the gate the answer is still being delivered
    rather than abandoned.
    """
    if is_cloud_model(model):
        yield _noop
        return
    if background:
        async with background_call():
            yield _noop
        return
    async with interactive_call() as entry:

        def keepalive() -> None:
            entry[0] = time.monotonic()

        yield keepalive


def _noop() -> None:
    """Keepalive for a call the gate does not track."""


class YieldedToInteractive(Exception):
    """A background call was abandoned so an interactive one could have the slot."""


async def run_yielding_to_interactive(coro, *, after_seconds: float):
    """Run a background coroutine, abandoning it if the user ends up waiting on it.

    Admission (`background_call`) decides whether to *start* a background call,
    and that is the whole story wherever a call is short. It is not the story on
    a host where one runs for a minute: a call admitted a second before the user
    asks anything is already in flight, and Ollama does not preempt (I-31), so
    the question queues behind it. Measured on an Intel i7-8850H: chat
    suggestions were generated at 11:51:20, a question arrived at 11:51:21, and
    48.5s of that question's 102s time-to-first-token was spent waiting for
    garnish to finish.

    Cancelling the client request is what frees the slot, and it genuinely does
    -- Ollama logs `srv stop: cancel task` and releases the slot immediately. A
    call cancelled at 12.0s here was followed by one served in 0.44s.

    Two states look alike from outside and must not be confused. A background
    call *waiting* in admission while a question runs is blocking nobody, and
    abandoning it would spend suggestion quality to buy latency nobody was
    losing -- on any host where a question outlasts the window, which is most of
    them. A call *in flight* when the question arrives is the one holding the
    slot. The discriminator is whether pressure was absent at some point while
    we ran: admission only admits when it is, so the timer arms only after that
    has been observed, and a call queued behind a question never arms at all.

    `after_seconds` is then continuous pressure *after arming*. A call that
    finishes inside the window can never be abandoned, which is what keeps this
    inert on hosts where background work is quick.

    Only for work that is cheap to lose and has a real fallback. Abandoning an
    enrichment call throws away minutes and leaves no equivalent second answer;
    abandoning suggestions costs one set of pills that templates then render.

    Raises:
        YieldedToInteractive: the call was abandoned; the caller must fall back.
    """
    task = asyncio.ensure_future(coro)
    armed = False
    pressure_since: float | None = None
    while True:
        done, _ = await asyncio.wait({task}, timeout=_POLL_SECONDS)
        if done:
            return task.result()
        if not under_interactive_pressure():
            # Admission admits only when this is true, so reaching here means the
            # call is running rather than queued behind someone's question.
            armed = True
            pressure_since = None
            continue
        if not armed:
            continue
        now = time.monotonic()
        if pressure_since is None:
            pressure_since = now
        elif now - pressure_since >= after_seconds:
            task.cancel()
            # The result is being discarded either way, and a provider error
            # raised by a call we just cancelled says nothing about the caller.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            raise YieldedToInteractive
