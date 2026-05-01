"""POST eval results to /monitoring/evals/store."""

import sys

import httpx


def store_results(
    backend_url: str,
    dataset: str,
    model: str,
    metrics: dict,
    eval_kind: str = "retrieval",
) -> None:
    """POST eval results to backend for storage."""
    payload = {
        "dataset_name": dataset,
        "model_used": model,
        "eval_kind": eval_kind,
        "hit_rate_5": metrics.get("hit_rate_5"),
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
    }
    try:
        resp = httpx.post(
            f"{backend_url}/monitoring/evals/store",
            json=payload,
            timeout=15.0,
        )
        resp.raise_for_status()
        print(f"\nResults stored. Run ID: {resp.json().get('id', '?')}")
    except Exception as exc:
        print(f"\nWARNING: failed to store results: {exc}", file=sys.stderr)
