"""Unit tests for summary eval metrics and persistence (S216)."""

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib.scoring_history import append_history  # noqa: E402
from evals.lib.summary_metrics import (  # noqa: E402
    compute_conciseness_pct,
    compute_no_hallucination,
    compute_theme_coverage,
)


def test_theme_coverage_counts_keyword_groups():
    summary = "Alice follows the rabbit into Wonderland and changes size."
    themes = ["alice", "rabbit|hare", "queen|cards", "size|change"]
    assert compute_theme_coverage(summary, themes) == pytest.approx(0.75)


def test_no_hallucination_from_mocked_judge_counts():
    assert compute_no_hallucination(hallucinated_count=0, total_claims=5) == 1.0
    assert compute_no_hallucination(hallucinated_count=1, total_claims=4) == 0.75


def test_conciseness_pct():
    assert compute_conciseness_pct("abcd", 8) == pytest.approx(0.5)
    assert compute_conciseness_pct("abcdefghijkl", 8) == pytest.approx(1.5)
    assert compute_conciseness_pct("abcd", 0) is None


def test_summary_history_persists_metrics(tmp_path):
    target = tmp_path / "scores.jsonl"
    append_history(
        "summaries",
        "judge",
        {
            "theme_coverage": 0.8,
            "no_hallucination": 0.9,
            "conciseness_pct": 1.1,
        },
        True,
        eval_kind="summary",
        path=target,
    )
    row = json.loads(target.read_text().strip())
    assert row["eval_kind"] == "summary"
    assert row["theme_coverage"] == 0.8
    assert row["no_hallucination"] == 0.9
    assert row["conciseness_pct"] == 1.1
