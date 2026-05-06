"""Unit tests for flashcard eval metrics (S217)."""

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib.flashcard_metrics import (  # noqa: E402
    compute_atomicity,
    compute_clarity_avg,
    compute_factuality,
    score_flashcards,
)
from evals.lib.scoring_history import append_history  # noqa: E402


def test_factuality_scorer_weights_partial():
    assert compute_factuality(["yes", "partial", "no", "yes"]) == pytest.approx(0.625)


def test_atomicity_scorer_fraction_yes():
    assert compute_atomicity([True, False, True, True]) == pytest.approx(0.75)


def test_clarity_avg_mean():
    assert compute_clarity_avg([5, 4, 3]) == pytest.approx(4.0)


def test_score_flashcards_with_mocked_judge():
    cards = [{"question": "q1", "answer": "a1"}, {"question": "q2", "answer": "a2"}]
    judgments = iter([
        {"factuality": "yes", "atomic": True, "clarity": 5},
        {"factuality": "partial", "atomic": False, "clarity": 3},
    ])
    metrics = score_flashcards(cards, "source", judge=lambda card, chunk: next(judgments))
    assert metrics["factuality"] == pytest.approx(0.75)
    assert metrics["atomicity"] == pytest.approx(0.5)
    assert metrics["clarity_avg"] == pytest.approx(4.0)


def test_flashcard_history_persists_metrics(tmp_path):
    target = tmp_path / "scores.jsonl"
    append_history(
        "flashcards",
        "judge",
        {"factuality": 0.9, "atomicity": 0.8, "clarity_avg": 4.2},
        True,
        eval_kind="flashcard",
        path=target,
    )
    row = json.loads(target.read_text().strip())
    assert row["eval_kind"] == "flashcard"
    assert row["factuality"] == 0.9
    assert row["atomicity"] == 0.8
    assert row["clarity_avg"] == 4.2
