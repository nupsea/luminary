"""Aggregating repeated runs, and refusing to call noise a result.

The rule these guard: a single generation run cannot resolve a change smaller
than the metric's own run-to-run spread, and two changes in this repo were once
credited with moving `citation_support_rate` by less than that.
"""

# ruff: noqa: E402, I001

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evals.lib.variance import aggregate, compare, resolves


def _rows(**series: list[float]) -> list[dict]:
    length = len(next(iter(series.values())))
    return [{k: v[i] for k, v in series.items()} for i in range(length)]


def test_sd_needs_two_runs_and_is_none_with_one():
    """A single run reports no spread, not a spread of zero: 0.0 would read as
    'perfectly stable' for something never repeated."""
    agg = aggregate(_rows(citation_support_rate=[0.65]))
    assert agg["n"] == 1
    assert agg["metrics"]["citation_support_rate"]["sd"] is None
    assert agg["metrics"]["citation_support_rate"]["mean"] == 0.65


def test_aggregate_reports_mean_spread_and_range():
    agg = aggregate(_rows(citation_support_rate=[0.5893, 0.7065, 0.6491, 0.6515]))
    stats = agg["metrics"]["citation_support_rate"]
    assert round(stats["mean"], 4) == 0.6491
    assert stats["sd"] > 0.04
    assert (stats["min"], stats["max"]) == (0.5893, 0.7065)


def test_a_deterministic_metric_that_moved_is_flagged_not_averaged():
    """HR@5 is bit-reproducible on a fixed corpus. A series where it moved
    measured two different systems, so its mean is meaningless."""
    agg = aggregate(_rows(hit_rate_5=[0.5750, 0.5500], citation_support_rate=[0.65, 0.70]))
    assert agg["unstable_deterministic"] == ["hit_rate_5"]


def test_a_stable_deterministic_metric_is_not_flagged():
    agg = aggregate(_rows(hit_rate_5=[0.5750, 0.5750, 0.5750]))
    assert agg["unstable_deterministic"] == []


def test_a_delta_inside_the_noise_is_not_a_result():
    """0.05 against sd 0.052 is the exact case that produced two false claims."""
    before = aggregate(_rows(citation_support_rate=[0.5893, 0.7065, 0.6491, 0.6515]))
    after = aggregate(_rows(citation_support_rate=[0.6393, 0.7565, 0.6991, 0.7015]))
    verdict = compare(before, after)["citation_support_rate"]
    assert round(verdict["delta"], 4) == 0.05
    assert verdict["resolved"] is False


def test_a_delta_larger_than_the_noise_resolves():
    before = aggregate(_rows(citation_support_rate=[0.5893, 0.7065, 0.6491, 0.6515]))
    after = aggregate(_rows(citation_support_rate=[0.8893, 1.0000, 0.9491, 0.9515]))
    verdict = compare(before, after)["citation_support_rate"]
    assert verdict["resolved"] is True


def test_comparison_uses_the_noisier_series():
    """Claiming a change resolved because the quieter arm was quiet is how a
    noise-sized delta gets published."""
    quiet = aggregate(_rows(m=[0.50, 0.50, 0.50, 0.51]))
    noisy = aggregate(_rows(m=[0.40, 0.60, 0.45, 0.65]))
    assert compare(quiet, noisy)["m"]["sd"] == noisy["metrics"]["m"]["sd"]


def test_no_spread_means_no_verdict_without_repetition():
    assert resolves(0.5, None) is False


def test_flags_and_aliases_are_not_metrics():
    """`rerank` is a bool and `hr5` duplicates `hit_rate_5`. Averaging either
    prints something that reads as a measurement and is not one."""
    rows = [
        {"hit_rate_5": 0.6, "hr5": 0.6, "rerank": False, "passed": True},
        {"hit_rate_5": 0.6, "hr5": 0.6, "rerank": False, "passed": True},
    ]
    assert set(aggregate(rows)["metrics"]) == {"hit_rate_5"}


def test_a_series_row_is_not_one_of_its_own_runs(tmp_path, monkeypatch):
    """The aggregate carries its members' run_group so it can be found again.
    Counting it as a member pulls the mean toward the mean."""
    import json

    sys.path.insert(0, str(REPO_ROOT / "evals"))
    import run_variance

    history = tmp_path / "scores_history.jsonl"
    rows = [
        {"eval_kind": "citation", "citation_support_rate": 0.60, "environment": {"run_group": "g1"}},
        {"eval_kind": "citation", "citation_support_rate": 0.70, "environment": {"run_group": "g1"}},
        {
            "eval_kind": "citation-series",
            "runs": 2,
            "citation_support_rate": 0.65,
            "environment": {"run_group": "g1"},
        },
    ]
    history.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr(run_variance, "SCORES_HISTORY_PATH", history)

    found = run_variance._history_rows("g1")
    assert len(found) == 2
    assert [r["citation_support_rate"] for r in found] == [0.60, 0.70]


# A judge grading its own output (asked 2026-08-15)


def test_a_run_where_one_model_answered_and_judged_is_named():
    from evals.lib.environment import self_judging

    env = {
        "judge_model": "ollama/qwen2.5:14b-instruct",
        "chat_model": "ollama/qwen2.5:14b-instruct",
        "generation_model": "ollama/qwen2.5:14b-instruct",
    }
    assert self_judging(env) == "ollama/qwen2.5:14b-instruct"


def test_a_different_judge_is_not_self_judging():
    from evals.lib.environment import self_judging

    env = {
        "judge_model": "ollama/qwen2.5:14b-instruct",
        "chat_model": "ollama/llama3.2",
        "generation_model": "ollama/llama3.2",
    }
    assert self_judging(env) is None


def test_a_run_with_no_judge_cannot_be_self_judging():
    """Retrieval-only runs score nothing with an LLM, so the question does not apply."""
    from evals.lib.environment import self_judging

    assert self_judging({"chat_model": "ollama/llama3.2"}) is None
