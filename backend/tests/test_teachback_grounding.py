"""Teach-back grades against the passage, not against the card's own answer.

Two defects, both already paid for on the flashcard path.

The evaluator never saw the source. It was given the card's answer and the
student's explanation, so it graded against a reference that may itself be
ungrounded -- measured on a real library, 26% of the cards quoting anything
quoted text absent from their document. `source_chunk_ids` makes the passage
recoverable, so the passage is what the explanation is graded against and the
card's answer is context rather than truth.

And the axis was undefined: "score 0 to 100" with nothing anchoring it. That is
the shape that returned `atomicity 1.0000` on a set two thirds of which carried
multi-point answers -- an undefined axis is answered with whatever is agreeable.

Never measured, either: no eval in this repo touches teach-back, so these are
contract tests on the prompt and the verification, not a quality claim.
"""

import pytest

from app.routers.study import (
    _CORRECTION_USER_TMPL,
    _TEACHBACK_SYSTEM,
    _TEACHBACK_USER_TMPL,
    _verified_evidence,
)

_PASSAGE = "Penelope undid her weaving each night for three years, so it was never finished."


class TestThePromptCarriesTheSource:
    def test_the_evaluator_is_given_the_passage(self):
        assert "{source}" in _TEACHBACK_USER_TMPL

    def test_the_correction_card_is_given_the_passage(self):
        """It asked for a `source_excerpt` while supplying no source, so every
        quote it produced was invented by construction -- the same defect as
        `fill_gaps`, which wrote cards from a section heading."""
        assert "{source}" in _CORRECTION_USER_TMPL

    def test_the_evaluator_is_told_to_judge_only_against_the_passage(self):
        assert "not against what you know" in _TEACHBACK_SYSTEM

    def test_the_score_bands_are_defined(self):
        """A bare 0-100 range is the least defined instruction there is."""
        for band in ("90-100", "70-89", "40-69", "1-39"):
            assert band in _TEACHBACK_USER_TMPL

    def test_an_empty_misconception_list_is_explicitly_allowed(self):
        """Asked for misconceptions with no way to say "none", a model invents one."""
        assert "do not invent one" in _TEACHBACK_USER_TMPL

    def test_the_evaluator_must_quote_rather_than_paraphrase(self):
        assert "word for word" in _TEACHBACK_USER_TMPL
        assert "do not paraphrase" in _TEACHBACK_USER_TMPL


class TestThePromptCarriesTheQuestion:
    """It did not, and completeness was measured against the whole passage.

    On a card asking why personal context matters, the stored missing_points
    were "creating a personalized workflow definition (agents.md)" and
    "demonstrating the iterative checking process with /skeptical" -- two topics
    the question did not raise. The learner scored 10/100 on completeness for
    answering exactly what was asked.
    """

    def test_the_evaluator_is_told_what_was_asked(self):
        assert "{question}" in _TEACHBACK_USER_TMPL

    def test_completeness_is_scored_against_the_question(self):
        assert "the question did not ask about is not" in _TEACHBACK_USER_TMPL

    def test_missing_points_may_not_range_beyond_the_question(self):
        assert "IN ANSWER TO THE QUESTION" in _TEACHBACK_USER_TMPL
        assert "Never list material the question did not ask about" in (
            _TEACHBACK_USER_TMPL.replace("\n", " ").replace("  ", " ")
        )


def test_the_model_is_not_asked_for_a_score():
    """The headline is computed from the dimensions printed under it
    (`_score_from_dimensions`). Asking for it as a fourth free integer is what
    produced a stored row reading `score` 0 against completeness 50."""
    assert '"score"' not in _TEACHBACK_USER_TMPL


class TestEvidenceIsVerified:
    def test_a_real_quote_survives(self):
        assert _verified_evidence({"evidence": "undid her weaving each night"}, _PASSAGE)

    def test_an_invented_quote_is_dropped(self):
        assert _verified_evidence({"evidence": "she wove for ten years"}, _PASSAGE) == ""

    def test_a_missing_quote_is_not_an_error(self):
        assert _verified_evidence({}, _PASSAGE) == ""

    def test_nothing_is_verified_when_there_is_no_passage(self):
        """With no source there is nothing to check against, so the quote cannot be
        presented as verified -- the same rule `grounding_state` follows."""
        assert _verified_evidence({"evidence": "undid her weaving each night"}, "") == ""


@pytest.mark.parametrize("field", ["correct_points", "missing_points", "misconceptions"])
def test_the_response_shape_is_unchanged(field):
    """The UI reads these; adding grounding must not move them."""
    assert field in _TEACHBACK_USER_TMPL


_STORY = (
    "Before her father married the Queen her stepmother, she and a Prince who lived in "
    "a nearby kingdom were spending time together. When he visited, they would take "
    "walks in the royal garden."
)
_STEPMOTHER_CARD = (
    "Who was Snow White spending time with before her father married the Queen's stepmother?"
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "kept"),
    [
        # Returned by the model on 2026-09-30 for the card it was correcting.
        (_STEPMOTHER_CARD, False),
        ("What did Snow White and the Prince do when he visited?", True),
        # Same passage as its card, different question: a real correction.
        ("What did Snow White and the Prince do before her father remarried?", True),
    ],
)
async def test_a_correction_card_that_repeats_its_card_is_dropped(question, kept):
    """The same question twice in one run teaches nothing and reads as a bug."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.routers.study import _insert_correction_flashcard

    card = SimpleNamespace(
        question=_STEPMOTHER_CARD,
        answer="a Prince who lived in a nearby kingdom.",
        source_excerpt="she and a Prince who lived in a nearby kingdom were spending time together",
        document_id="doc",
        chunk_id="chunk",
        source_chunk_ids=["chunk"],
    )
    payload = {
        "question": question,
        "answer": "They took walks in the royal garden.",
        "source_excerpt": "When he visited, they would take walks in the royal garden."
        if "visited" in question
        else card.source_excerpt,
    }
    session = MagicMock()
    with patch("app.routers.study._sync_flashcard_fts", AsyncMock()):
        new_id = await _insert_correction_flashcard(card, payload, session, _STORY)

    assert (new_id is not None) is kept
    assert session.add.called is kept
