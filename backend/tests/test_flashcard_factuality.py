"""A real quote does not make the answer true.

`grounding` proves the card quotes text that exists. This is the other half: does
the answer follow from that text. It is the only flashcard check that needs a
model, which makes *which* model the load-bearing decision -- measured on 59 live
cards, phi4-mini called 54 of them supported and granite3.2:8b called 53, agreeing
with a 14B on the pass/fail call 0.41 and 0.42 of the time. A gate built on either
certifies exactly what it was added to catch, so there is no small-model default
and an unnamed checker does not run at all.
"""

from unittest.mock import AsyncMock

import pytest

from app.services.flashcard_factuality import (
    FACTUALITY_SUPPORTED,
    FACTUALITY_UNSUPPORTED,
    FACTUALITY_UNVERIFIABLE,
    _parse_verdict,
    check_answer,
    is_self_judging,
)

_PASSAGE = "Penelope undid her weaving each night for three years."


def _llm(response: str | None = None, *, raises: Exception | None = None):
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=raises) if raises else AsyncMock(return_value=response)
    return llm


class TestVerdictParsing:
    def test_a_clean_verdict_is_read(self):
        assert _parse_verdict('{"verdict": "yes"}') == "yes"

    def test_prose_around_the_json_is_tolerated(self):
        assert _parse_verdict('Sure!\n{"verdict":"no"}\n') == "no"

    def test_a_bare_word_is_read_when_unambiguous(self):
        assert _parse_verdict("no") == "no"

    def test_an_ambiguous_answer_is_not_a_verdict(self):
        """'yes ... no ...' must not resolve to whichever word came first."""
        assert _parse_verdict("yes for the first part, no for the second") is None

    def test_unparseable_output_never_defaults_to_a_pass(self):
        for raw in ("", None, "I cannot determine that", "{}"):
            assert _parse_verdict(raw) is None


@pytest.mark.asyncio
async def test_a_supported_answer_passes():
    verdict = await check_answer(
        "How did Penelope delay the suitors?",
        "She undid her weaving each night.",
        _PASSAGE,
        checker="ollama/qwen2.5:14b-instruct",
        llm=_llm('{"verdict": "yes"}'),
    )
    assert verdict == FACTUALITY_SUPPORTED


@pytest.mark.asyncio
async def test_a_partly_supported_answer_is_not_a_pass():
    """Half-supported means the card asserts something the passage does not, and a
    learner reviewing it for a year has no way to find out which half."""
    verdict = await check_answer(
        "How long did Penelope delay the suitors?",
        "Ten years, until Telemachus returned.",
        _PASSAGE,
        checker="ollama/qwen2.5:14b-instruct",
        llm=_llm('{"verdict": "partial"}'),
    )
    assert verdict == FACTUALITY_UNSUPPORTED


@pytest.mark.asyncio
async def test_an_unreachable_checker_yields_unverifiable_not_a_pass():
    verdict = await check_answer(
        "q", "a", _PASSAGE,
        checker="ollama/qwen2.5:14b-instruct",
        llm=_llm(raises=ConnectionError("ollama is down")),
    )
    assert verdict == FACTUALITY_UNVERIFIABLE


@pytest.mark.asyncio
async def test_garbage_from_the_checker_yields_unverifiable_not_a_pass():
    verdict = await check_answer(
        "q", "a", _PASSAGE,
        checker="ollama/qwen2.5:14b-instruct",
        llm=_llm("I think it is probably fine"),
    )
    assert verdict == FACTUALITY_UNVERIFIABLE


@pytest.mark.asyncio
async def test_no_passage_is_unverifiable_and_costs_no_call():
    llm = _llm('{"verdict": "yes"}')
    verdict = await check_answer("q", "a", "", checker="ollama/x", llm=llm)
    assert verdict == FACTUALITY_UNVERIFIABLE
    llm.generate.assert_not_awaited()


def test_the_guard_reads_the_model_that_will_actually_generate(monkeypatch):
    """The override is empty on the default path -- which is exactly where a
    checker collides with the generator. Comparing against the override let a 14B
    judge its own cards while the guard reported no self-judging."""
    from app.services import flashcard_factuality as fact
    from app.services import model_router

    monkeypatch.setattr(
        model_router,
        "resolve",
        lambda role, **kw: type("C", (), {"model": "ollama/qwen2.5:14b-instruct"})(),
    )
    assert fact.effective_generation_model() == "ollama/qwen2.5:14b-instruct"
    assert is_self_judging("ollama/qwen2.5:14b-instruct", fact.effective_generation_model())


class TestSelfJudging:
    def test_the_generator_may_not_check_its_own_cards(self):
        assert is_self_judging("ollama/qwen3.5:4b", "ollama/qwen3.5:4b")

    def test_a_different_model_may(self):
        assert not is_self_judging("ollama/qwen2.5:14b-instruct", "ollama/qwen3.5:4b")

    def test_an_unset_checker_is_not_self_judging(self):
        assert not is_self_judging("", "ollama/qwen3.5:4b")


@pytest.mark.asyncio
async def test_the_screen_does_nothing_when_no_checker_is_configured(monkeypatch):
    """An unnamed checker must not silently become a small default: measured, the
    small local models pass ~90% of everything."""
    from app.services import flashcard_generators as gen

    monkeypatch.setattr(gen, "factuality_model", lambda: "")
    cards = [{"question": "q", "answer": "a"}]
    assert await gen._screen_factuality(cards, "some passage") == cards


@pytest.mark.asyncio
async def test_the_screen_refuses_to_let_a_model_grade_its_own_cards(monkeypatch, caplog):
    from app.services import flashcard_generators as gen

    monkeypatch.setattr(gen, "factuality_model", lambda: "ollama/qwen3.5:4b")
    monkeypatch.setattr(gen, "effective_generation_model", lambda: "ollama/qwen3.5:4b")
    cards = [{"question": "q", "answer": "a"}]
    assert await gen._screen_factuality(cards, "some passage") == cards
    assert "grade its own cards" in caplog.text


@pytest.mark.asyncio
async def test_the_screen_drops_unsupported_cards_and_labels_the_rest(monkeypatch):
    from app.services import flashcard_generators as gen

    monkeypatch.setattr(gen, "factuality_model", lambda: "ollama/qwen2.5:14b-instruct")
    monkeypatch.setattr(gen, "effective_generation_model", lambda: "ollama/qwen3.5:4b")
    monkeypatch.setattr(gen, "_get_llm_service", lambda: AsyncMock())

    verdicts = iter([FACTUALITY_SUPPORTED, FACTUALITY_UNSUPPORTED, FACTUALITY_UNVERIFIABLE])

    async def _fake(question, answer, passage, *, checker, llm):
        return next(verdicts)

    monkeypatch.setattr(gen, "check_answer", _fake)
    cards = [{"question": f"q{i}", "answer": "a"} for i in range(3)]
    kept = await gen._screen_factuality(cards, "some passage")

    assert [c["question"] for c in kept] == ["q0", "q2"]
    assert [c["factuality"] for c in kept] == [FACTUALITY_SUPPORTED, FACTUALITY_UNVERIFIABLE]
