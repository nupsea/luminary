"""Intent routing accuracy eval runner (S218)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.lib.intent_metrics import (  # noqa: E402
    compute_per_route_precision_recall,
    compute_routing_accuracy,
)
from evals.lib.loader import load_golden  # noqa: E402
from evals.lib.schemas import IntentGoldenEntry  # noqa: E402
from evals.lib.scoring_history import append_history  # noqa: E402
from evals.lib.store import store_results  # noqa: E402

THRESHOLDS = {"routing_accuracy": 0.85}


def classify(backend_url: str, question: str) -> str:
    resp = httpx.post(f"{backend_url}/qa/classify-only", json={"question": question}, timeout=15.0)
    resp.raise_for_status()
    return resp.json()["chosen_route"]


def print_table(metrics: dict) -> None:
    print(f"\n{'=' * 58}")
    print("  Intent routing evaluation")
    print(f"{'=' * 58}")
    print(f"  routing_accuracy      {metrics['routing_accuracy']:.4f}")
    for route, vals in metrics["per_route"].items():
        print(
            f"  {route:<12} precision={vals['precision']:.4f} recall={vals['recall']:.4f}"
        )
    print(f"{'=' * 58}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run chat route classification eval.")
    parser.add_argument("--dataset", default="intents")
    parser.add_argument("--backend-url", default="http://localhost:8000")
    parser.add_argument("--assert-thresholds", action="store_true")
    args = parser.parse_args()

    rows = load_golden(args.dataset, IntentGoldenEntry)
    samples = []
    for row in rows:
        samples.append(
            {
                "question": row["question"],
                "expected_route": row["expected_route"],
                "predicted_route": classify(args.backend_url, row["question"]),
            }
        )

    metrics = {
        "routing_accuracy": compute_routing_accuracy(samples),
        "per_route": compute_per_route_precision_recall(samples),
    }
    passed = metrics["routing_accuracy"] >= THRESHOLDS["routing_accuracy"]
    append_history(args.dataset, "classifier", metrics, passed, eval_kind="routing")
    store_results(args.backend_url, args.dataset, "classifier", metrics, eval_kind="routing")
    print_table(metrics)
    if args.assert_thresholds and not passed:
        print(
            f"QUALITY GATE FAILED: routing_accuracy {metrics['routing_accuracy']:.4f} < "
            f"{THRESHOLDS['routing_accuracy']}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
