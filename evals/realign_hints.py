"""Helper: dump top-5 retrieved chunks for entries whose context_hint is not
in the question's top-5 results. Used to manually pick a corrected hint that
points to a passage retrieval actually surfaces and that genuinely supports
the ground_truth_answer.

Not a metric runner. One-shot diagnostic for S212 iteration 7.

Usage::
    cd evals
    uv run python realign_hints.py --dataset book_time_machine --backend-url http://localhost:7820
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from run_eval import (  # noqa: PLC0415 -- intentional: same-dir module
    GOLDEN_DIR,
    _norm,
    load_golden,
    load_manifest,
)


def search(backend_url: str, question: str, doc_id: str | None, limit: int = 5) -> list[dict]:
    params: dict[str, object] = {"q": question, "limit": limit}
    if doc_id:
        params["document_id"] = doc_id
    try:
        resp = httpx.get(f"{backend_url}/search", params=params, timeout=30.0)
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        print(f"  ERROR: /search failed: {exc}", file=sys.stderr)
        return []
    matches: list[dict] = []
    for group in body.get("results", []):
        if doc_id and group.get("document_id") != doc_id:
            continue
        for m in group.get("matches", []):
            matches.append(m)
    matches.sort(key=lambda m: m.get("relevance_score", 0.0), reverse=True)
    return matches[:limit]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", required=True)
    p.add_argument("--backend-url", default="http://localhost:7820", dest="backend_url")
    p.add_argument("--limit", type=int, default=5)
    args = p.parse_args()

    rows = load_golden(args.dataset)
    manifest = load_manifest()

    out_path = Path(__file__).parent / f".realign_{args.dataset}.txt"
    with out_path.open("w") as f:
        for i, row in enumerate(rows, start=1):
            question = row["question"]
            gt = row["ground_truth_answer"]
            existing_hint = row.get("context_hint", "")
            doc_id = manifest.get(row.get("source_file", ""))
            chunks = search(args.backend_url, question, doc_id, limit=args.limit)
            hint_norm = _norm(existing_hint)[:80]
            in_top_k = any(hint_norm in _norm(m.get("text", "")) for m in chunks)
            if in_top_k:
                continue
            f.write(f"\n=== [{i}] (current hint not in top-{args.limit}) ===\n")
            f.write(f"Q: {question}\n")
            f.write(f"GT: {gt}\n")
            f.write(f"OLD HINT: {existing_hint}\n")
            for j, m in enumerate(chunks, start=1):
                text = m.get("text", "").replace("\n", " ")
                f.write(f"  [{j}] {text[:600]}\n")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
