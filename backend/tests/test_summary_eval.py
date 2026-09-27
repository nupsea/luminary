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
from evals.run_summary_eval import (  # noqa: E402
    FetchedSummary,
    parse_summary_stream,
    summary_author,
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


def test_the_done_event_carries_source_and_serving_model():
    body = (
        'data: {"token": "A short "}\n\n'
        'data: {"token": "summary."}\n\n'
        'data: {"done": true, "cached": false, "source": "generated", "model": "ollama/m"}\n\n'
    )
    fetched = parse_summary_stream(body)
    assert fetched == FetchedSummary("A short summary.", "generated", "ollama/m")


def _gen(model: str | None = None) -> FetchedSummary:
    return FetchedSummary("text", "generated", model)


def test_a_replayed_or_assembled_summary_is_credited_to_no_model():
    """#154: scoring a stored summary filed the row under the judge model."""
    for source in ("cached", "assembled", None):
        stale = FetchedSummary("text", source, None)
        assert summary_author([_gen("ollama/a"), stale], "ollama/a", "ollama/a") is None


def test_a_generated_summary_is_credited_to_the_model_that_served_it():
    assert summary_author([_gen("ollama/served")], "ollama/asked", "ollama/chat") == (
        "ollama/served"
    )
    # A backend that could not name the server: the requested model, else the route's.
    assert summary_author([_gen()], "ollama/asked", "ollama/chat") == "ollama/asked"
    assert summary_author([_gen()], None, "ollama/chat") == "ollama/chat"
    assert summary_author([_gen()], None, None) is None


def test_summaries_written_by_two_models_name_no_single_author():
    """A fallback mid-run means the row describes neither model."""
    assert summary_author([_gen("ollama/a"), _gen("ollama/b")], None, "ollama/a") is None
