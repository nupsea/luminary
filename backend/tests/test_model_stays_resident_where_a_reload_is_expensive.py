"""An evicted model must not be the user's problem on a host that reloads slowly.

Measured on an Intel i7-8850H in a 12GB Docker VM, loading qwen3.5:4b took
anywhere from 9.59s to 155.45s, and 86.25s of it landed inside one real
question. The spread is not a page-cache effect (35.5s/21.7s with caches dropped
against 48.9s/12.7s retained), so the load is not a cost to tune but one to stop
paying.

The gate reads a start-up probe rather than a load, because the two cannot be
told apart from inside the app and both are the user's wait: that host's probes
measured 84.03s, 91.07s and 107.47s, and the 91.07s one paid no load at all --
it was a 25-token generation losing its cores to the embedder, GLiNER and the
reranker.

Ollama evicts after OLLAMA_KEEP_ALIVE (30m) and nothing re-warms after startup,
so a question asked after a break paid that load. One did: 261s end to end, 86
of them a model load -- reported by the graph as

    [perf] classify_node LLM fallback took 94.10s

while the classifier's own work in that call was 189 prompt tokens and 4
generated ones, 6.6s. That misattribution is why it was hunted in the
classifier twice and never found there.

The gate is the warm-up's own measurement of *this* host, never a platform or
CPU check -- so a fast host starts no loop and is unaffected, and a slow one is
covered whether it is Intel, a VM, or anything else that loads slowly.
"""

import asyncio
import inspect

import pytest

from app.config import Settings, get_settings
from app.services import model_keepwarm, warmup


@pytest.fixture(autouse=True)
def _forget_measurement():
    model_keepwarm.reset_measurement()
    yield
    model_keepwarm.reset_measurement()


class TestTheGateIsAMeasurement:
    def test_an_unmeasured_host_keeps_todays_behaviour(self):
        """Unmeasured is not 'fast'. Defaulting it either way would be a guess
        about a machine nobody has timed."""
        assert model_keepwarm.measured_probe_seconds() is None
        assert not model_keepwarm.local_inference_is_slow()

    def test_a_fast_host_never_starts_the_loop(self):
        """The whole constraint: this must change nothing where nothing is wrong."""
        model_keepwarm.record_startup_probe(3.0)
        assert not model_keepwarm.local_inference_is_slow()

    def test_the_fastest_load_seen_on_the_slow_host_stays_below_the_line(self):
        """9.59s was the quickest load measured there. A host that loads that
        fast is not one where anybody waits, so it is deliberately not covered
        -- the gate reads the start-up probe, which on that host was 84-107s."""
        model_keepwarm.record_startup_probe(9.59)
        assert not model_keepwarm.local_inference_is_slow()

    def test_the_load_that_cost_a_user_86s_is_above_the_line(self):
        """The case the fix exists for: 86.25s of one 261s question."""
        model_keepwarm.record_startup_probe(86.25)
        assert model_keepwarm.local_inference_is_slow()

    def test_the_threshold_still_admits_that_load(self):
        """Raising it past a real measured load turns the fix off silently."""
        assert Settings().LLM_KEEP_WARM_ABOVE_SECONDS <= 86.25

    def test_nothing_here_branches_on_the_platform(self):
        """A CPU or platform check would be a guess about the cause; the
        warm-up is a measurement of the effect."""
        # The module docstring names the hardware it was measured on and the
        # check it deliberately does not perform, so read the code without it.
        code = inspect.getsource(model_keepwarm).replace(model_keepwarm.__doc__ or "", "")
        for banned in ("platform.machine", "processor()", "arm64", "x86_64", "Intel"):
            assert banned not in code, (
                f"{banned!r} makes the gate a guess about hardware rather than a "
                "measurement of this host"
            )


class TestAFastHostIsUntouched:
    """The constraint this change is held to: an M-series, Windows or Linux host
    that already reloads quickly must behave exactly as it did before."""

    @pytest.mark.asyncio
    async def test_the_loop_returns_instead_of_running(self):
        """It must terminate, not idle: a loop left running on every host would
        be a behaviour change on hosts with nothing wrong."""
        model_keepwarm.record_startup_probe(3.0)
        await asyncio.wait_for(model_keepwarm.keep_warm_loop(), timeout=5.0)

    @pytest.mark.asyncio
    async def test_the_loop_issues_no_llm_call_at_all(self, monkeypatch):
        """No extra inference, no extra Ollama traffic, no pinned residency."""
        called = False

        def _boom():
            nonlocal called
            called = True
            raise AssertionError("a fast host must never be pinged")

        monkeypatch.setattr("app.services.llm.get_llm_service", _boom)
        model_keepwarm.record_startup_probe(3.0)
        await asyncio.wait_for(model_keepwarm.keep_warm_loop(), timeout=5.0)
        assert called is False

    @pytest.mark.asyncio
    async def test_an_unmeasured_host_is_also_untouched(self, monkeypatch):
        """A host whose warm-up never reported -- an offline Ollama, a cloud-only
        install -- must not be pinged on a guess."""
        monkeypatch.setattr(
            "app.services.llm.get_llm_service",
            lambda: (_ for _ in ()).throw(AssertionError("pinged an unmeasured host")),
        )
        await asyncio.wait_for(model_keepwarm.keep_warm_loop(), timeout=5.0)


class TestThePingYieldsToTheUser:
    @pytest.mark.asyncio
    async def test_no_ping_while_an_interactive_call_is_in_flight(self, monkeypatch):
        """One serving slot (I-31): a ping issued during an Ask is latency the
        user pays for a timer that call is already resetting."""
        monkeypatch.setattr(
            "app.services.llm_admission.under_interactive_pressure", lambda: True
        )
        assert await model_keepwarm._ping_if_idle() is False

    @pytest.mark.asyncio
    async def test_no_ping_when_a_real_call_already_reset_the_timer(self, monkeypatch):
        """Ollama's timer is reset by any generation, not only by ours."""
        import time

        class _State:
            last_interactive_end = time.monotonic()

        monkeypatch.setattr(
            "app.services.llm_admission.under_interactive_pressure", lambda: False
        )
        monkeypatch.setattr("app.services.llm_admission.current_state", lambda: _State())
        assert await model_keepwarm._ping_if_idle() is False

    @pytest.mark.asyncio
    async def test_an_idle_host_is_pinged_with_a_bounded_ping(self, monkeypatch):
        """It resets a timer; it does not produce text."""
        monkeypatch.setattr(
            "app.services.llm_admission.under_interactive_pressure", lambda: False
        )
        monkeypatch.setattr("app.services.llm_admission.current_state", lambda: None)

        seen: dict = {}

        class _LLM:
            async def generate(self, prompt, **kwargs):
                seen.update(kwargs)
                return "ok"

        monkeypatch.setattr("app.services.llm.get_llm_service", lambda: _LLM())
        assert await model_keepwarm._ping_if_idle() is True
        assert seen["max_tokens"] == 1, "an unbounded ping decodes at the host's rate"


class TestTheWiringCannotBeDropped:
    def test_warmup_records_what_the_startup_probe_cost(self):
        """Without this the gate has nothing to read and the loop never runs."""
        source = inspect.getsource(warmup)
        assert "record_startup_probe" in source

    def test_the_ping_interval_stays_inside_the_keep_alive_window(self):
        """OLLAMA_KEEP_ALIVE is 30m on every install path in this repo. An
        interval at or past it races the eviction it exists to prevent."""
        assert get_settings().LLM_KEEP_WARM_INTERVAL_SECONDS <= 900.0
