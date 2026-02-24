"""RAGAS evaluation runner for Luminary golden datasets.

Usage::
    uv run python run_eval.py --dataset book --model ollama/mistral
    uv run python run_eval.py --dataset paper --backend-url http://localhost:8000
"""

import argparse
import json
import sys
from pathlib import Path

import httpx
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

GOLDEN_DIR = Path(__file__).parent / "golden"
VALID_DATASETS = ["book", "paper", "conversation", "notes", "code"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_golden(dataset: str) -> list[dict]:
    path = GOLDEN_DIR / f"{dataset}.jsonl"
    if not path.exists():
        print(f"ERROR: golden file not found: {path}", file=sys.stderr)
        sys.exit(1)
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def post_qa(backend_url: str, question: str, model: str) -> dict:
    """POST to /qa and return the response JSON (or empty dict on failure)."""
    try:
        resp = httpx.post(
            f"{backend_url}/qa",
            json={"question": question, "document_ids": None, "model": model},
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"  WARNING: /qa call failed: {exc}", file=sys.stderr)
        return {}


def compute_hit_rate_5(samples: list[dict]) -> float:
    """HR@5: fraction of questions where ground_truth substring is in top-5 contexts."""
    if not samples:
        return 0.0
    hits = 0
    for s in samples:
        ground_truth = s.get("ground_truths", [""])[0].lower()
        contexts = s.get("contexts", [])[:5]
        if any(ground_truth[:50] in ctx.lower() for ctx in contexts):
            hits += 1
    return hits / len(samples)


def compute_mrr(samples: list[dict]) -> float:
    """MRR: mean reciprocal rank of first chunk containing ground_truth."""
    if not samples:
        return 0.0
    reciprocal_ranks = []
    for s in samples:
        ground_truth = s.get("ground_truths", [""])[0].lower()
        contexts = s.get("contexts", [])
        rank = None
        for i, ctx in enumerate(contexts, start=1):
            if ground_truth[:50] in ctx.lower():
                rank = i
                break
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
    return sum(reciprocal_ranks) / len(reciprocal_ranks)


def store_results(backend_url: str, dataset: str, model: str, metrics: dict) -> None:
    """POST eval results to backend for storage."""
    payload = {
        "dataset_name": dataset,
        "model_used": model,
        "hit_rate_5": metrics.get("hit_rate_5"),
        "mrr": metrics.get("mrr"),
        "faithfulness": metrics.get("faithfulness"),
        "answer_relevance": metrics.get("answer_relevance"),
        "context_precision": metrics.get("context_precision"),
        "context_recall": metrics.get("context_recall"),
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


def print_table(dataset: str, model: str, metrics: dict) -> None:
    print(f"\n{'=' * 56}")
    print(f"  RAGAS evaluation — dataset={dataset}  model={model}")
    print(f"{'=' * 56}")
    for key, val in metrics.items():
        if val is not None:
            print(f"  {key:<22}  {val:.4f}")
        else:
            print(f"  {key:<22}  n/a")
    print(f"{'=' * 56}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation against a golden dataset.")
    parser.add_argument(
        "--dataset",
        choices=VALID_DATASETS,
        required=True,
        help="Golden dataset name",
    )
    parser.add_argument(
        "--model",
        default="ollama/mistral",
        help="LiteLLM model string (default: ollama/mistral)",
    )
    parser.add_argument(
        "--backend-url",
        default="http://localhost:8000",
        dest="backend_url",
        help="Luminary backend URL",
    )
    args = parser.parse_args()

    rows = load_golden(args.dataset)
    print(f"Loaded {len(rows)} examples from {args.dataset}.jsonl")

    samples: list[dict] = []
    for i, row in enumerate(rows, start=1):
        question = row["question"]
        ground_truth = row["ground_truth_answer"]
        print(f"  [{i}/{len(rows)}] Querying: {question[:60]}...")
        qa_resp = post_qa(args.backend_url, question, args.model)
        answer = qa_resp.get("answer", "")
        # contexts = list of chunk texts from citations
        citations = qa_resp.get("citations", [])
        contexts = [c.get("text", "") for c in citations if isinstance(c, dict)] or [""]
        samples.append(
            {
                "question": question,
                "answer": answer,
                "contexts": contexts,
                "ground_truths": [ground_truth],
            }
        )

    # Custom metrics (no LLM required)
    hr5 = compute_hit_rate_5(samples)
    mrr = compute_mrr(samples)

    # RAGAS metrics (require LLM judge — graceful fallback if unavailable)
    ragas_scores: dict[str, float | None] = {
        "faithfulness": None,
        "answer_relevance": None,
        "context_precision": None,
        "context_recall": None,
    }
    try:
        dataset_hf = Dataset.from_list(samples)
        result = evaluate(
            dataset=dataset_hf,
            metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        )
        scores = result.to_pandas()
        for col in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
            if col in scores.columns:
                val = float(scores[col].mean())
                key = "answer_relevance" if col == "answer_relevancy" else col
                ragas_scores[key] = val
    except Exception as exc:
        print(f"WARNING: RAGAS scoring failed (LLM may be unavailable): {exc}", file=sys.stderr)

    metrics = {
        "hit_rate_5": hr5,
        "mrr": mrr,
        **ragas_scores,
    }

    print_table(args.dataset, args.model, metrics)
    store_results(args.backend_url, args.dataset, args.model, metrics)


if __name__ == "__main__":
    main()
