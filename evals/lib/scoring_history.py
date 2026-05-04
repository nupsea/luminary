"""Local scores_history.jsonl append helper."""

import json
from datetime import UTC, datetime
from pathlib import Path

SCORES_HISTORY_PATH = Path(__file__).resolve().parent.parent / "scores_history.jsonl"


def append_history(
    dataset: str,
    model: str,
    metrics: dict,
    passed: bool,
    eval_kind: str = "retrieval",
    *,
    path: Path | None = None,
) -> None:
    """Append one eval run to scores_history.jsonl.

    *eval_kind* defaults to "retrieval" so existing callers continue working.
    *path* override is for unit testing against a tmp file.
    """
    target = path if path is not None else SCORES_HISTORY_PATH
    entry = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "dataset": dataset,
        "model": model,
        "eval_kind": eval_kind,
        "hr5": metrics.get("hit_rate_5"),
        "mrr": metrics.get("mrr"),
        "faithfulness": metrics.get("faithfulness"),
        "answer_relevance": metrics.get("answer_relevance"),
        "context_precision": metrics.get("context_precision"),
        "context_recall": metrics.get("context_recall"),
        "citation_support_rate": metrics.get("citation_support_rate"),
        "theme_coverage": metrics.get("theme_coverage"),
        "no_hallucination": metrics.get("no_hallucination"),
        "conciseness_pct": metrics.get("conciseness_pct"),
        "factuality": metrics.get("factuality"),
        "atomicity": metrics.get("atomicity"),
        "clarity_avg": metrics.get("clarity_avg"),
        "routing_accuracy": metrics.get("routing_accuracy"),
        "per_route": metrics.get("per_route"),
        "ablation_metrics": metrics.get("ablation_metrics"),
        "passed": passed,
    }
    with target.open("a") as f:
        f.write(json.dumps(entry) + "\n")
