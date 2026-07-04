"""Unit tests for cross-model golden verification (evals.lib.golden_verify)."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib.golden_verify import (  # noqa: E402
    cross_verify,
    failed_axes,
    parse_verdict,
)


def test_parse_verdict_handles_fenced_json():
    raw = '```json\n{"answerable": true, "answer_correct": true, "self_contained": false}\n```'
    assert parse_verdict(raw) == {
        "answerable": True,
        "answer_correct": True,
        "self_contained": False,
    }


def test_parse_verdict_defaults_missing_axes_false():
    assert parse_verdict('{"answerable": true}') == {
        "answerable": True,
        "answer_correct": False,
        "self_contained": False,
    }


def test_cross_verify_unanimous_pass():
    judge = lambda m, q, a, c: {  # noqa: E731
        "answerable": True,
        "answer_correct": True,
        "self_contained": True,
    }
    passed, verdicts = cross_verify(
        question="q", answer="a", context="c", models=["m1", "m2"], judge=judge
    )
    assert passed is True
    assert set(verdicts) == {"m1", "m2"}
    assert failed_axes(verdicts) == []


def test_cross_verify_one_dissent_fails_and_reports_axis():
    def judge(m, q, a, c):
        if m == "m2":
            return {"answerable": True, "answer_correct": False, "self_contained": True}
        return {"answerable": True, "answer_correct": True, "self_contained": True}

    passed, verdicts = cross_verify(
        question="q", answer="a", context="c", models=["m1", "m2"], judge=judge
    )
    assert passed is False
    assert "answer_correct" in failed_axes(verdicts)


def test_cross_verify_judge_error_counts_as_fail():
    def judge(m, q, a, c):
        raise RuntimeError("model down")

    passed, verdicts = cross_verify(
        question="q", answer="a", context="c", models=["m1"], judge=judge
    )
    assert passed is False
    assert verdicts["m1"]["error"] == "model down"
