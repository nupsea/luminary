"""Unit tests for evals.lib.runners.NliFaithfulnessEval.

The HHEM model is mocked -- these assert the whole-answer aggregation, the
premise = joined-context / hypothesis = answer contract, provenance, and the
graceful-skip paths. A real-model check lives behind the ``slow`` marker.
"""

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import evals.lib.runners as runners  # noqa: E402
from evals.lib.runners import NliFaithfulnessEval  # noqa: E402


class _FakeScorer:
    model_name = "fake/hhem"

    def __init__(self) -> None:
        self.seen_pairs: list[tuple[str, str]] = []

    def score_pairs(self, pairs):
        self.seen_pairs = list(pairs)
        return [0.9 for _ in pairs]


def _patch_scorer(monkeypatch, scorer):
    monkeypatch.setattr(runners, "_get_faithfulness_scorer", lambda: scorer)


def test_whole_answer_aggregation_and_provenance(monkeypatch):
    scorer = _FakeScorer()
    _patch_scorer(monkeypatch, scorer)
    samples = [
        {"answer": "The sky is blue.", "contexts": ["The sky appears blue.", "Rayleigh."]},
        {"answer": "Grass is green.", "contexts": ["Grass is green."]},
    ]

    out = NliFaithfulnessEval().run(samples)

    assert out["faithfulness"] == pytest.approx(0.9)
    assert out["faithfulness_model"] == "fake/hhem"
    # premise = joined contexts, hypothesis = answer, one pair per sample.
    assert scorer.seen_pairs == [
        ("The sky appears blue.\nRayleigh.", "The sky is blue."),
        ("Grass is green.", "Grass is green."),
    ]


def test_mean_over_samples(monkeypatch):
    class _Varying(_FakeScorer):
        def score_pairs(self, pairs):
            self.seen_pairs = list(pairs)
            return [1.0, 0.0, 0.5]

    _patch_scorer(monkeypatch, _Varying())
    samples = [{"answer": f"a{i}", "contexts": ["c"]} for i in range(3)]

    out = NliFaithfulnessEval().run(samples)

    assert out["faithfulness"] == pytest.approx(0.5)


def test_blank_answers_skipped(monkeypatch):
    scorer = _FakeScorer()
    _patch_scorer(monkeypatch, scorer)
    samples = [
        {"answer": "   ", "contexts": ["c"]},
        {"answer": "real", "contexts": ["c"]},
    ]

    out = NliFaithfulnessEval().run(samples)

    assert len(scorer.seen_pairs) == 1
    assert scorer.seen_pairs[0][1] == "real"
    assert out["faithfulness"] == pytest.approx(0.9)


def test_no_answers_returns_none(monkeypatch):
    scorer = _FakeScorer()
    _patch_scorer(monkeypatch, scorer)

    out = NliFaithfulnessEval().run([{"answer": "", "contexts": ["c"]}])

    assert out == {"faithfulness": None, "faithfulness_model": None}
    assert scorer.seen_pairs == []


def test_scorer_failure_is_graceful(monkeypatch):
    class _Boom:
        model_name = "fake/hhem"

        def score_pairs(self, pairs):
            raise RuntimeError("model load failed")

    _patch_scorer(monkeypatch, _Boom())

    out = NliFaithfulnessEval().run([{"answer": "x", "contexts": ["c"]}])

    assert out == {"faithfulness": None, "faithfulness_model": None}


def test_missing_contexts_defaults_to_empty_premise(monkeypatch):
    scorer = _FakeScorer()
    _patch_scorer(monkeypatch, scorer)

    out = NliFaithfulnessEval().run([{"answer": "x"}])

    assert scorer.seen_pairs == [("", "x")]
    assert out["faithfulness"] == pytest.approx(0.9)


@pytest.mark.slow
def test_nli_faithfulness_live_model():
    """Real HHEM load + score. Downloads ~600MB on first run."""
    ctx = ["Paris is the capital of France."]
    samples = [
        {"answer": "The capital of France is Paris.", "contexts": ctx},
        {"answer": "The capital of France is Berlin.", "contexts": ctx},
    ]
    out = NliFaithfulnessEval().run(samples)
    assert out["faithfulness"] is not None
    assert out["faithfulness_model"]
