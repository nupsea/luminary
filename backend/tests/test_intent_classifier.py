"""Tests for the S77 intent classifier (app/services/intent.py).

(a) test_summary_keywords_detected: each keyword triggers intent='summary'.
(b) test_comparative_keywords_detected: comparative keywords detected.
(c) test_relational_keywords_detected: relational keywords detected.
(d) test_low_confidence_triggers_llm_fallback: mock LiteLLM → intent='factual'.
(e) test_llm_fallback_offline_defaults_to_factual: LiteLLM raises → 'factual'.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.intent import (
    _SUMMARY_KWS,
    _llm_classify_fallback,
    classify_intent_heuristic,
)

# ---------------------------------------------------------------------------
# (a) test_summary_keywords_detected
# ---------------------------------------------------------------------------


def test_summary_keywords_detected():
    """Every keyword in the summary set triggers intent='summary' with confidence >= 0.9."""
    for kw in _SUMMARY_KWS:
        intent, conf = classify_intent_heuristic(f"please {kw} the document")
        assert intent == "summary", f"Expected 'summary' for keyword {kw!r}, got {intent!r}"
        assert conf >= 0.9


# ---------------------------------------------------------------------------
# (b) test_comparative_keywords_detected
# ---------------------------------------------------------------------------


def test_comparative_keywords_detected():
    """Representative comparative keywords trigger intent='comparative'."""
    # Use keywords that don't also match relational or summary first
    comparative_samples = ["compare", "difference between", "versus", "similarities"]
    for kw in comparative_samples:
        intent, conf = classify_intent_heuristic(f"what is the {kw} between A and B")
        assert intent == "comparative", (
            f"Expected 'comparative' for keyword {kw!r}, got {intent!r}"
        )


# ---------------------------------------------------------------------------
# (c) test_relational_keywords_detected
# ---------------------------------------------------------------------------


def test_relational_keywords_detected():
    """Representative relational keywords trigger intent='relational'."""
    relational_samples = ["relation between", "connection between", "what is the relationship"]
    for kw in relational_samples:
        intent, conf = classify_intent_heuristic(f"explain the {kw} between A and B")
        assert intent == "relational", (
            f"Expected 'relational' for keyword {kw!r}, got {intent!r}"
        )


# ---------------------------------------------------------------------------
# (d) test_low_confidence_triggers_llm_fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_low_confidence_triggers_llm_fallback():
    """A question with no keywords (confidence=0.5) → LLM fallback is used.
    Mock LiteLLM to return 'factual' → final intent is 'factual'.
    """
    # Verify no-keyword question gives exploratory (confidence=0.5 < 0.7)
    intent, confidence = classify_intent_heuristic("What do you think about that?")
    assert intent == "exploratory"
    assert confidence < 0.7

    # Mock LLM to return 'factual'
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = "factual"

    with patch("litellm.acompletion", return_value=mock_response):
        result = await _llm_classify_fallback(
            "What do you think about that?", default="exploratory"
        )

    assert result == "factual"


# ---------------------------------------------------------------------------
# (e) test_llm_fallback_offline_defaults_to_factual
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_fallback_offline_defaults_to_factual():
    """LiteLLM raises an exception (Ollama offline) → fallback returns 'factual'."""
    with patch("litellm.acompletion", side_effect=Exception("connection refused")):
        result = await _llm_classify_fallback("some vague question", default="exploratory")

    assert result == "factual"


# ---------------------------------------------------------------------------
# Extra: heuristic ordering — summary before factual
# ---------------------------------------------------------------------------


def test_summary_beats_factual_for_what_is_this_about():
    """'what is this about' matches summary before factual keywords."""
    intent, _ = classify_intent_heuristic("what is this about?")
    assert intent == "summary"


def test_exploratory_for_unknown_question():
    """A question with no matching keywords → exploratory with confidence=0.5."""
    intent, confidence = classify_intent_heuristic("Tell me something interesting.")
    assert intent == "exploratory"
    assert confidence == 0.5


# ---------------------------------------------------------------------------
# New ACs: 'summary' word alone, and 'how does'/'how do' not relational
# ---------------------------------------------------------------------------


def test_summary_keyword_alone():
    """'summary' as a standalone word triggers intent='summary' with confidence=0.9."""
    for question in [
        "what is the summary of this book?",
        "provide a summary",
        "give me a summary",
        "the summary of this document",
    ]:
        intent, conf = classify_intent_heuristic(question)
        assert intent == "summary", f"Expected 'summary' for {question!r}, got {intent!r}"
        assert conf == 0.9


def test_factual_question_not_relational():
    """Questions with 'how does'/'how do' must NOT classify as relational."""
    factual_questions = [
        "how does the main character escape?",
        "how does FSRS scheduling work?",
        "how do the gods intervene in the story?",
    ]
    for q in factual_questions:
        intent, _ = classify_intent_heuristic(q)
        assert intent != "relational", (
            f"Expected non-relational for {q!r}, got {intent!r}"
        )
