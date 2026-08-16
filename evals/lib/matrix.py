"""Which metrics may decide a model swap, and whether two models are separable.

Three tiers, from the plan's calibration stage:

- **Structural** gates a swap. Parse rate before repair, repair-kind counts,
  requested-count adherence, citation validity, non-empty answer rate, routing
  accuracy against a labelled golden. All of these move with the model and none
  of them is a matter of taste.
- **Quality** is reported and never gates. A cross-model faithfulness delta is a
  style artifact -- this repo spent a model decision learning that, when a 0.2
  HHEM gap between llama3.2 and qwen turned out to be phrasing.
- **Excluded** never appears. hit_rate, MRR and nDCG have no generation-model
  term in them, so including them lets retrieval noise be attributed to a model.

The separation test is the acceptance criterion for the instrument itself: two
models of visibly different size must produce visibly different numbers. If they
do not, the instrument is blind and no model may be chosen on it.
"""

from __future__ import annotations

from typing import Any

STRUCTURAL: frozenset[str] = frozenset(
    {
        "first_pass_rate",
        "parse_failure_rate",
        "cards_requested",
        "cards_generated",
        "generation_rate",
        "answer_rate",
        "citation_coverage",
        "citations_dropped",
        "citations_proposed",
        "citations_gated",
        "uncited_answers",
        "qa_failed_calls",
        "qa_not_found_calls",
        "qa_answered_calls",
        # Measured against a hand-labelled golden, so it is not a style artifact
        # the way a judged score is. That is why it may gate.
        "routing_accuracy",
    }
)

QUALITY: frozenset[str] = frozenset(
    {
        "faithfulness",
        "answer_relevance",
        "citation_support_rate",
        "factuality",
        "atomicity",
        "clarity_avg",
        "theme_coverage",
        "no_hallucination",
        "conciseness_pct",
        "summary_grounding",
    }
)

EXCLUDED: frozenset[str] = frozenset(
    {
        "hr5",
        "hit_rate_5",
        "mrr",
        "ndcg_10",
        "boundary_misses",
        "context_precision",
        "context_recall",
    }
)

# Structural in shape, but contaminated by library state rather than by the
# model: the near-duplicate filter drops candidates resembling cards the document
# already has, so the same passage yields fewer cards on every re-run. Reported,
# never allowed to decide a separation.
LIBRARY_STATE_DEPENDENT: frozenset[str] = frozenset({"cards_returned", "cards_deduped"})

# A rate must move this far to count as a difference between two models; a count
# must move this far in relative terms and by at least `_COUNT_MIN_ABSOLUTE`.
RATE_MARGIN = 0.05
COUNT_RELATIVE_MARGIN = 0.10
COUNT_MIN_ABSOLUTE = 2.0


def metric_name(key: str) -> str:
    """The metric itself, with any `task.` prefix the matrix added removed."""
    return key.split(".", 1)[1] if "." in key else key


def tier(key: str) -> str:
    """Which tier a metric key belongs to: structural, quality, excluded, other."""
    key = metric_name(key)
    if key.startswith("repair_") or key in ("parses", "parses_repaired", "parses_first_pass"):
        return "structural"
    if key in STRUCTURAL:
        return "structural"
    if key in QUALITY:
        return "quality"
    if key in EXCLUDED:
        return "excluded"
    return "other"


_RATE_SUFFIXES = ("_rate", "_coverage", "_accuracy")


def _is_rate(key: str) -> bool:
    """Rates are decided by name, never by value.

    A count that happens to be 0 or 1 sits inside [0, 1] and would otherwise be
    judged against a rate's margin, turning one failed call in forty into a
    difference between two models.
    """
    return metric_name(key).endswith(_RATE_SUFFIXES)


def differs(key: str, a: float, b: float) -> bool:
    """Whether two values of the same metric are far enough apart to mean something."""
    delta = abs(a - b)
    if _is_rate(key):
        return delta >= RATE_MARGIN
    scale = max(abs(a), abs(b), 1.0)
    return delta >= COUNT_MIN_ABSOLUTE and (delta / scale) >= COUNT_RELATIVE_MARGIN


def structural_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    """The numeric structural metrics of a run, excluding the library-state ones."""
    out: dict[str, float] = {}
    for key, value in metrics.items():
        if metric_name(key) in LIBRARY_STATE_DEPENDENT or tier(key) != "structural":
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        out[key] = float(value)
    return out


def separation(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """What, if anything, tells two models apart on the structural tier.

    Returns the per-metric deltas and a verdict. `separated: False` is a finding
    about the instrument, not about the models -- go back and add metrics until
    it can see the difference, and do not choose a model in the meantime.
    """
    left, right = structural_metrics(a), structural_metrics(b)
    shared = sorted(set(left) & set(right))
    deltas = [
        {
            "metric": key,
            "a": left[key],
            "b": right[key],
            "delta": right[key] - left[key],
            "significant": differs(key, left[key], right[key]),
        }
        for key in shared
    ]
    separating = [d["metric"] for d in deltas if d["significant"]]
    return {
        "compared": shared,
        "only_in_a": sorted(set(left) - set(right)),
        "only_in_b": sorted(set(right) - set(left)),
        "deltas": deltas,
        "separating_metrics": separating,
        "separated": bool(separating),
    }
