"""Flashcard correctness eval runner (S217)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from evals.lib.flashcard_metrics import judge_flashcard, score_flashcards  # noqa: E402
from evals.lib.loader import load_golden  # noqa: E402
from evals.lib.manifest import ensure_ingested, load_manifest  # noqa: E402
from evals.lib.schemas import FlashcardGoldenEntry  # noqa: E402
from evals.lib.scoring_history import append_history  # noqa: E402
from evals.lib.store import store_results  # noqa: E402

THRESHOLDS = {"factuality": 0.85, "atomicity": 0.80, "clarity_avg": 3.5}


def generate_cards(backend_url: str, document_id: str, row: dict) -> list[dict]:
    payload = {
        "document_id": document_id,
        "scope": "full",
        "count": row.get("expected_card_count") or 1,
        "context": row["chunk_id_or_text"],
    }
    resp = httpx.post(f"{backend_url}/flashcards/generate", json=payload, timeout=120.0)
    resp.raise_for_status()
    return resp.json()


def print_table(dataset: str, metrics: dict) -> None:
    print(f"\n{'=' * 58}")
    print(f"  Flashcard evaluation -- dataset={dataset}")
    print(f"{'=' * 58}")
    for key, val in metrics.items():
        print(f"  {key:<22}  {val:.4f}" if val is not None else f"  {key:<22}  n/a")
    print(f"{'=' * 58}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run flashcard correctness eval.")
    parser.add_argument("--dataset", default="flashcards")
    parser.add_argument("--backend-url", default="http://localhost:8000")
    parser.add_argument("--judge-model", default=get_settings().LITELLM_DEFAULT_MODEL)
    parser.add_argument("--assert-thresholds", action="store_true")
    args = parser.parse_args()

    rows = load_golden(args.dataset, FlashcardGoldenEntry)
    manifest = load_manifest()
    per_row: list[dict] = []
    for row in rows:
        doc_id = ensure_ingested(args.backend_url, row["source_file"], manifest)
        if not doc_id:
            continue
        cards = generate_cards(args.backend_url, doc_id, row)
        per_row.append(
            score_flashcards(
                cards,
                row["chunk_id_or_text"],
                judge=lambda card, chunk: judge_flashcard(card, chunk, args.judge_model),
            )
        )

    metrics = {
        "factuality": sum(s["factuality"] or 0.0 for s in per_row) / len(per_row),
        "atomicity": sum(s["atomicity"] or 0.0 for s in per_row) / len(per_row),
        "clarity_avg": sum(s["clarity_avg"] or 0.0 for s in per_row) / len(per_row),
    }
    violations = [
        f"{key} {metrics[key]:.4f} < {threshold}"
        for key, threshold in THRESHOLDS.items()
        if metrics[key] < threshold
    ]
    passed = len(violations) == 0
    append_history(args.dataset, args.judge_model, metrics, passed, eval_kind="flashcard")
    store_results(args.backend_url, args.dataset, args.judge_model, metrics, eval_kind="flashcard")
    print_table(args.dataset, metrics)
    if args.assert_thresholds and violations:
        for violation in violations:
            print(f"QUALITY GATE FAILED: {violation}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
