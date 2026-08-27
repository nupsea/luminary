"""The intent classifier's LLM fallback is gated on a measurement of the host.

Below confidence 0.7 the heuristic is guessing and an LLM decides. That call is
free on a GPU box and is not free here: measured on an Intel i7-8850H with the
model already resident -- `/api/ps` showed one model and the log has no load --
`classify_node` spent 17.02s of a 50.12s question returning `summary`, which is
the label `classify_intent_heuristic` had already returned at 0.50. About 8s of
that is this host's floor for issuing any local call at all, the same floor the
keep-warm ping measures, and no prompt or output bound reaches it.

The gate is `local_inference_is_slow()` -- the same measured fact as the
keep-warm loop and the context budget, not a third threshold that could drift
from them. Unmeasured is not slow.

What the gate costs is measured, not assumed, against a live backend running the
model the app ships (`ollama/qwen3.5:4b`, 2026-08-27), fallback on -> off:

    intents (50)              1.0000 -> 1.0000   the LLM changes nothing
    intents_adversarial (29)  0.8966 -> 0.8276   2 rescues lost

Measure this arm on the model in `chat_model` and on no other. The same 29 rows
score 0.9655 on `qwen2.5:14b-instruct` and 0.8276 on `qwen3.5:0.8b`
(`evals/scores_history.jsonl`), so a delta taken across two models prices the
gate at a cost no user pays.

`intents` carries the committed threshold (routing_accuracy >= 0.85) and does
not move, because the 2 of 50 rows that reach the LLM there are ones the
heuristic already routes correctly. `QA_INTENT_LLM_FALLBACK_ON_SLOW_HOST` buys
the adversarial rescues back at ~17s per affected question.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.services import model_keepwarm
from app.services.intent import (
    LLM_FALLBACK_BELOW,
    classify_intent_heuristic,
    should_use_llm_fallback,
)


@pytest.fixture(autouse=True)
def _clear_probe():
    model_keepwarm.reset_measurement()
    yield
    model_keepwarm.reset_measurement()


def _slow():
    model_keepwarm.record_startup_probe(get_settings().LLM_KEEP_WARM_ABOVE_SECONDS + 1.0)


def _quick():
    model_keepwarm.record_startup_probe(get_settings().LLM_KEEP_WARM_ABOVE_SECONDS - 1.0)


def test_a_confident_heuristic_never_asks_the_llm_on_any_host():
    """The gate must not change what happens above the threshold."""
    for setup in (_quick, _slow, model_keepwarm.reset_measurement):
        setup()
        use_llm, why = should_use_llm_fallback(0.95)
        assert use_llm is False
        assert why == "heuristic confident"


def test_an_unmeasured_host_still_asks_the_llm():
    """None is 'unmeasured', never 'slow' -- a host whose Ollama was down at
    start-up keeps the shipped behaviour rather than silently losing a check."""
    use_llm, _ = should_use_llm_fallback(0.5)
    assert use_llm is True


def test_a_quick_host_still_asks_the_llm():
    _quick()
    use_llm, _ = should_use_llm_fallback(0.5)
    assert use_llm is True


def test_an_expensive_host_keeps_its_17_seconds():
    _slow()
    use_llm, why = should_use_llm_fallback(0.5)
    assert use_llm is False
    assert "slow host" in why


def test_the_reason_carries_the_probe_that_decided_it():
    """A route that looks wrong is diagnosed from this string."""
    _slow()
    _, why = should_use_llm_fallback(0.5)
    assert "probe" in why


def test_the_setting_buys_the_rescues_back(monkeypatch):
    """Turning a check off is a decision: the flag exists so a slow host that
    wants the 4 adversarial rescues can pay 17s for them."""
    _slow()
    settings = get_settings()
    monkeypatch.setattr(settings, "QA_INTENT_LLM_FALLBACK_ON_SLOW_HOST", True)
    use_llm, _ = should_use_llm_fallback(0.5)
    assert use_llm is True


def test_the_gate_only_ever_applies_below_the_threshold():
    """Bracketing the two cases: at the threshold the heuristic decides on every
    host, one step below it the host's measurement decides."""
    _slow()
    assert should_use_llm_fallback(LLM_FALLBACK_BELOW)[0] is False
    assert should_use_llm_fallback(LLM_FALLBACK_BELOW)[1] == "heuristic confident"
    assert should_use_llm_fallback(LLM_FALLBACK_BELOW - 0.01)[0] is False
    assert "slow host" in should_use_llm_fallback(LLM_FALLBACK_BELOW - 0.01)[1]


# -- the spelling gap the gate would otherwise expose -------------------------
#
# With the fallback gated off, a summary request the heuristic misses no longer
# gets corrected -- it routes to search, which is a wrong answer rather than a
# slow one. "summarise" was exactly that case: _inflected_regex adds only an
# optional (e)s to a keyword, so of the eight spellings of the verb only two
# matched.


@pytest.mark.parametrize(
    "question",
    [
        "Summarise the main argument in two sentences.",
        "Summarize the main argument in two sentences.",
        "Can you summarise this for me?",
        "I summarised it already, do it properly",
        "Summarising this document, what stands out?",
        "Summarizing the whole thing, what stands out?",
    ],
)
def test_every_spelling_of_the_verb_reaches_summary_without_an_llm(question):
    intent, confidence = classify_intent_heuristic(question)
    assert intent == "summary"
    assert confidence >= LLM_FALLBACK_BELOW, "must not need the LLM to be routed"


@pytest.mark.parametrize(
    "question",
    [
        # The bracketing counter-cases. The pattern matches the VERB, so a noun
        # that merely starts the same way must not drag an unrelated question
        # into summary -- "summarily" is the one that shares the most letters.
        "Was the appeal dismissed summarily?",
        "What is a summariser in this architecture?",
    ],
)
def test_a_word_that_merely_starts_the_same_is_not_a_summary_request(question):
    intent, _ = classify_intent_heuristic(question)
    assert intent != "summary"
