"""Aggregate repeated eval runs, and say whether a difference is resolvable.

Generation metrics move between identical runs: measured over four runs of one
frozen build, `citation_support_rate` has sd 0.052 on `book` and 0.025 on
`paper`, and `citations_proposed` ranged 49-71 across those runs. A single run
therefore cannot resolve a change smaller than about 0.10 on book or 0.05 on
paper, and two structural changes were once credited with moving it by less than
that. Both were noise.

Retrieval metrics are exempt -- they are bit-reproducible on a fixed corpus --
which is why a series that disagrees on `hit_rate_5` is reported as a corpus or
funnel change rather than averaged into a mean.
"""

from __future__ import annotations

import statistics
from typing import Any

# Metrics that must be identical across a series on one library state. A spread
# here is not variance to average; it means the thing being measured changed.
DETERMINISTIC = ("hit_rate_5", "mrr", "ndcg_10")

# `hr5` duplicates `hit_rate_5` in the history schema; aggregating both prints
# one metric twice under two names.
ALIASES = ("hr5",)

# How many standard deviations a difference must clear to count as resolved.
# Two sd on a normal-ish spread is ~95%: below it, the honest answer is that the
# run count is too small, not that nothing changed.
RESOLVE_SD = 2.0


def _is_measurement(value: Any) -> bool:
    """A bool is a flag, not a measurement: averaging `rerank` reports 0.0."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def _numeric(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [float(r[key]) for r in rows if _is_measurement(r.get(key))]


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """mean / sd / min / max per metric over a series of runs.

    `sd` is the sample standard deviation, which needs at least two runs; with
    one it is None rather than 0.0. A zero would read as "perfectly stable" for
    a measurement that has not been repeated.
    """
    if not rows:
        return {"n": 0, "metrics": {}, "unstable_deterministic": []}

    keys = {k for r in rows for k, v in r.items() if _is_measurement(v) and k not in ALIASES}
    metrics: dict[str, dict[str, float | None]] = {}
    for key in sorted(keys):
        values = _numeric(rows, key)
        if not values:
            continue
        metrics[key] = {
            "mean": statistics.fmean(values),
            "sd": statistics.stdev(values) if len(values) > 1 else None,
            "min": min(values),
            "max": max(values),
            "n": len(values),
        }

    unstable = [
        key
        for key in DETERMINISTIC
        if key in metrics and metrics[key]["sd"] is not None and metrics[key]["sd"] > 0
    ]
    return {"n": len(rows), "metrics": metrics, "unstable_deterministic": unstable}


def resolves(delta: float, sd: float | None) -> bool:
    """Is a difference larger than the noise it was measured against."""
    if sd is None:
        return False
    if sd == 0:
        return delta != 0
    return abs(delta) >= RESOLVE_SD * sd


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Per-metric delta between two aggregates, against the noise of both.

    The sd used is the larger of the two series': claiming a change resolved
    because the quieter series was quiet is how a noise-sized delta gets
    published as a result.
    """
    out: dict[str, Any] = {}
    for key, after_stats in after.get("metrics", {}).items():
        before_stats = before.get("metrics", {}).get(key)
        if before_stats is None:
            continue
        delta = after_stats["mean"] - before_stats["mean"]
        sds = [s for s in (before_stats["sd"], after_stats["sd"]) if s is not None]
        sd = max(sds) if sds else None
        out[key] = {
            "before": before_stats["mean"],
            "after": after_stats["mean"],
            "delta": delta,
            "sd": sd,
            "resolved": resolves(delta, sd),
        }
    return out
