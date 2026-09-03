"""A metric that could not be computed must not report a score (I-32).

Each case here is a real default that was in the code: a judge failure or a
missing input produced a number, so a hole in the measurement was reported as a
result. Every one of them is silent -- nothing in the output said the value was
invented.
"""

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib.flashcard_metrics import score_flashcards  # noqa: E402
from evals.lib.summary_metrics import (  # noqa: E402
    compute_no_hallucination,
    compute_theme_coverage,
)


class TestNothingCheckedIsNotAPerfectScore:
    def test_zero_claims_yields_none(self):
        """`max(total_claims, 1)` made an empty check score 1.0.

        The caller refuses to default a *failed* judge to a perfect score, but a
        judge that succeeds and finds nothing to check went straight through it.
        """
        assert compute_no_hallucination(0, 0) is None

    def test_a_real_count_still_scores(self):
        assert compute_no_hallucination(1, 4) == 0.75

    def test_no_themes_yields_none(self):
        assert compute_theme_coverage("any summary", []) is None

    def test_themes_present_still_score(self):
        assert compute_theme_coverage("a summary about keys", ["keys|locks"]) == 1.0
        assert compute_theme_coverage("a summary about doors", ["keys|locks"]) == 0.0


class TestAFailedCardJudgeIsExcludedNotScoredWorst:
    """`judge_flashcard` defaulted a missing verdict to "no" and clarity to 1.

    Both are the worst value on their axis, so a judge answering in an
    unexpected shape reported the model as producing false, unclear cards.
    """

    CARDS = [
        {"question": "q1", "answer": "One fact."},
        {"question": "q2", "answer": "Another fact."},
    ]

    def test_one_failed_card_does_not_drag_the_score(self):
        calls = {"n": 0}

        def _judge(_card, _chunk):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("flashcard judge returned an unusable factuality: ''")
            return {"factuality": "yes", "clarity": 5, "atomic": True}

        out = score_flashcards(self.CARDS, "source", judge=_judge)

        assert out["factuality"] == 1.0, "the failed card must be excluded, not scored 'no'"
        assert out["clarity_avg"] == 5.0
        assert out["judge_failures"] == 1

    def test_every_card_failing_yields_none_rather_than_zero(self):
        def _judge(_card, _chunk):
            raise ValueError("unusable")

        out = score_flashcards(self.CARDS, "source", judge=_judge)

        assert out["factuality"] is None
        assert out["clarity_avg"] is None
        assert out["judge_failures"] == 2

    def test_structural_atomicity_survives_a_failed_judge(self):
        """It needs no model, so a judge outage must not remove it."""

        def _judge(_card, _chunk):
            raise ValueError("unusable")

        out = score_flashcards(self.CARDS, "source", judge=_judge)

        assert out["atomicity"] is not None

    def test_disagreement_is_measured_only_over_judged_cards(self):
        """It compares the judge's opinion against the structural answer.

        A card the judge never scored has no opinion to compare, and padding one
        in would manufacture agreement or disagreement that nobody expressed.
        """
        calls = {"n": 0}

        def _judge(_card, _chunk):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("unusable")
            return {"factuality": "yes", "clarity": 4, "atomic": False}

        out = score_flashcards(self.CARDS, "source", judge=_judge)

        # One judged card, structurally atomic, judged not atomic -> full disagreement.
        assert out["judge_atomicity_disagreement"] == 1.0


class TestTheJudgeRefusesAnUnusableShape:
    @pytest.mark.parametrize(
        "payload",
        [
            {"clarity": 5, "atomic": True},  # no factuality
            {"factuality": "maybe", "clarity": 5, "atomic": True},  # not in the set
            {"factuality": "yes", "atomic": True},  # no clarity
            {"factuality": "yes", "clarity": 5},  # no atomic
        ],
    )
    def test_missing_or_unknown_fields_raise(self, payload, monkeypatch):
        import json as _json

        import evals.lib.flashcard_metrics as fm

        class _Msg:
            content = _json.dumps(payload)

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        monkeypatch.setitem(
            sys.modules,
            "litellm",
            type("L", (), {"completion": staticmethod(lambda **kw: _Resp())}),
        )

        with pytest.raises(ValueError):
            fm.judge_flashcard({"question": "q", "answer": "a"}, "chunk", "some/model")
