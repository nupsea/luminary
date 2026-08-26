"""Garnish must not hold the only slot while the user waits behind it.

Admission decides whether to *start* a background call, and that is the whole
story wherever one is short. It is not the story on a host where one runs for a
minute. Measured on an Intel i7-8850H in a 12GB Docker VM: chat suggestions were
generated at 11:51:20 and a question arrived at 11:51:21, so the suggestions call
was already in flight. Ollama does not preempt (I-31), and 48.5s of that
question's 102s time-to-first-token was spent waiting for six suggested
questions nobody had asked for.

Cancelling the client request is what frees the slot, and it does: Ollama logs
`srv stop: cancel task` and releases it. A call cancelled at 12.0s here was
followed by one served in 0.44s.

The trap this file mostly exists to guard is the other direction. A background
call *waiting* in admission while a question runs is blocking nobody, and
abandoning it would degrade suggestions to templates on every host where a
question outlasts the window -- which is most of them, including the fast ones
this must not touch.
"""

import asyncio

import pytest

from app.config import Settings
from app.services import llm_admission
from app.services.llm_admission import (
    YieldedToInteractive,
    run_yielding_to_interactive,
)


@pytest.fixture
def pressure(monkeypatch):
    """Drive `under_interactive_pressure()` from the test."""
    state = {"on": False}
    monkeypatch.setattr(
        llm_admission, "under_interactive_pressure", lambda: state["on"]
    )
    monkeypatch.setattr(llm_admission, "_POLL_SECONDS", 0.01)
    return state


class TestTheCallIsAbandonedWhenItIsTheOneBlocking:
    @pytest.mark.asyncio
    async def test_a_question_arriving_mid_call_abandons_it(self, pressure):
        """The incident: admitted while idle, then someone asks."""

        async def slow():
            await asyncio.sleep(10)
            return "suggestions"

        async def ask_shortly():
            await asyncio.sleep(0.05)
            pressure["on"] = True

        asyncio.create_task(ask_shortly())
        with pytest.raises(YieldedToInteractive):
            await run_yielding_to_interactive(slow(), after_seconds=0.05)

    @pytest.mark.asyncio
    async def test_the_underlying_call_is_actually_cancelled(self, pressure):
        """Abandoning without cancelling would free nothing: the slot is only
        released when the client request goes away."""
        cancelled = asyncio.Event()

        async def slow():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def ask_shortly():
            await asyncio.sleep(0.05)
            pressure["on"] = True

        asyncio.create_task(ask_shortly())
        with pytest.raises(YieldedToInteractive):
            await run_yielding_to_interactive(slow(), after_seconds=0.05)
        assert cancelled.is_set()


class TestAQueuedCallIsNeverAbandoned:
    """The regression this design exists to avoid, and the reason the timer arms
    rather than simply counting pressure."""

    @pytest.mark.asyncio
    async def test_pressure_present_for_the_whole_call_does_not_abandon_it(
        self, pressure
    ):
        """A call waiting in admission behind a long question is blocking nobody.
        Abandoning it would degrade suggestions on every host where a question
        outlasts the window."""
        pressure["on"] = True

        async def queued():
            await asyncio.sleep(0.3)
            return "suggestions"

        assert await run_yielding_to_interactive(queued(), after_seconds=0.05) == (
            "suggestions"
        )

    @pytest.mark.asyncio
    async def test_it_arms_only_after_pressure_clears(self, pressure):
        """Queued, then admitted, then a *new* question arrives while it runs --
        that one is blocking, so it is abandoned."""
        pressure["on"] = True

        async def slow():
            await asyncio.sleep(10)

        async def clear_then_ask_again():
            await asyncio.sleep(0.05)
            pressure["on"] = False
            await asyncio.sleep(0.05)
            pressure["on"] = True

        asyncio.create_task(clear_then_ask_again())
        with pytest.raises(YieldedToInteractive):
            await run_yielding_to_interactive(slow(), after_seconds=0.05)


class TestAQuickHostIsUntouched:
    @pytest.mark.asyncio
    async def test_a_call_that_finishes_inside_the_window_is_never_abandoned(
        self, pressure
    ):
        """The structural guarantee: a host whose suggestions call completes
        before the window elapses cannot abandon one, whatever the user does."""

        async def quick():
            await asyncio.sleep(0.02)
            return "suggestions"

        async def ask_immediately():
            pressure["on"] = True

        asyncio.create_task(ask_immediately())
        assert await run_yielding_to_interactive(quick(), after_seconds=5.0) == (
            "suggestions"
        )

    @pytest.mark.asyncio
    async def test_no_pressure_at_all_returns_the_result(self, pressure):
        async def quick():
            return "suggestions"

        assert await run_yielding_to_interactive(quick(), after_seconds=0.05) == (
            "suggestions"
        )

    @pytest.mark.asyncio
    async def test_the_error_still_reaches_the_caller(self, pressure):
        """Abandoning must not swallow a genuine failure into a silent fallback."""

        async def boom():
            raise ValueError("model said no")

        with pytest.raises(ValueError, match="model said no"):
            await run_yielding_to_interactive(boom(), after_seconds=0.05)


class TestTheWindowIsNotZero:
    def test_the_default_leaves_a_quick_call_room_to_finish(self):
        """At zero this abandons on any pressure at all, which spends suggestion
        quality to buy latency nobody was losing."""
        assert Settings().LLM_BACKGROUND_YIELD_AFTER_SECONDS >= 3.0

    def test_it_is_shorter_than_the_wait_it_replaces(self):
        """48.5s was the measured wait. A window near it buys nothing."""
        assert Settings().LLM_BACKGROUND_YIELD_AFTER_SECONDS <= 10.0


class TestSuggestionsUseIt:
    def test_the_suggestion_call_is_wrapped(self):
        """Unwrapped, the whole mechanism is dead code."""
        import inspect

        from app.services import suggestion_service

        source = inspect.getsource(suggestion_service)
        assert "run_yielding_to_interactive" in source
        assert "YieldedToInteractive" in source

    def test_abandoning_returns_empty_rather_than_raising(self):
        """Both callers already read empty as 'templates answer instead'; raising
        LLMUnavailableError would log a lie about why."""
        import inspect

        from app.services import suggestion_service

        source = inspect.getsource(suggestion_service.SuggestionService)
        assert "except YieldedToInteractive:" in source
        block = source.split("except YieldedToInteractive:", 1)[1][:400]
        assert "return []" in block
