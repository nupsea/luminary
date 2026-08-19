"""Collect answers for human labelling (E10).

Every generation floor in this repo is a collapse detector -- `mean - 3sd` --
because nothing establishes what a *good* answer looks like. `faithfulness` sits
at 0.30 because the observed distribution is unimodal, with no gap between
grounded and hallucinated answers to place a bar in, and the citation judge
scores its own notion of support with nothing establishing that notion is right.

One labelled set fixes all three: it validates the judge, makes a real
faithfulness bar derivable, and anchors the structural tier.

This script only *collects*. It runs `/qa` over golden questions spread across
content kinds, captures the answer together with the context the product actually
retrieved and the citations it emitted, and writes one JSON object per answer
with the verdict fields left null. Labelling is a separate, human step -- a model
labelling the set that exists to validate a model judge would be circular, and
the resulting bar would certify whatever the labeller already believed.

Usage::

    python evals/collect_faithfulness_labels.py --per-dataset 12 --out labels.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from evals.lib.environment import capture as capture_environment  # noqa: E402
from evals.lib.manifest import load_manifest  # noqa: E402
from evals.run_eval import post_qa  # noqa: E402

# Spread across content kinds on purpose. A faithfulness bar derived from one
# genre is a bar for that genre: prose fiction, a textbook and a contract fail
# differently, and the citation gap between models showed up identically on all
# three, which is what made it unarguable.
DEFAULT_DATASETS = ("book", "d2l", "paper", "legal", "conversation")


def _load(dataset: str) -> list[dict]:
    path = REPO_ROOT / "evals" / "golden" / f"{dataset}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def collect(backend_url: str, datasets: list[str], per_dataset: int, model: str) -> list[dict]:
    manifest = load_manifest()
    rows: list[dict] = []
    for dataset in datasets:
        entries = _load(dataset)
        if not entries:
            print(f"  {dataset}: no golden file, skipping", file=sys.stderr)
            continue
        # Evenly spaced rather than the first N: goldens are written in document
        # order, so the head of the file is the head of the document.
        stride = max(1, len(entries) // per_dataset)
        picked = entries[::stride][:per_dataset]
        for entry in picked:
            document_id = entry.get("source_document_id") or manifest.get(
                entry.get("source_file", "")
            )
            t0 = time.time()
            payload = post_qa(backend_url, entry["question"], model, document_id)
            answer = (payload.get("answer") or "").strip()
            context = payload.get("context") or payload.get("context_chunks") or []
            citations = payload.get("citations") or []
            rows.append({
                "dataset": dataset,
                "question": entry["question"],
                "document_id": document_id,
                "answer": answer,
                # What the model was actually given. A label about grounding is a
                # statement about this text, not about the document.
                "context": [
                    (c.get("text") if isinstance(c, dict) else str(c)) for c in context
                ],
                "citations": [
                    {
                        "excerpt": (c.get("excerpt") if isinstance(c, dict) else str(c)),
                        "chunk_id": (c.get("chunk_id") if isinstance(c, dict) else None),
                    }
                    for c in citations
                ],
                "elapsed_s": round(time.time() - t0, 1),
                # Filled by a human. Left null so an unlabelled row is visibly
                # unlabelled rather than defaulting to a verdict.
                "label_grounded": None,
                "label_citation_supported": [None] * len(citations),
                "labeller": None,
                "label_note": None,
            })
            print(
                f"  {dataset:<12} {len(answer):>5} chars, {len(context)} chunks, "
                f"{len(citations)} citations, {rows[-1]['elapsed_s']}s",
                file=sys.stderr,
            )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend-url", default="http://localhost:7820")
    ap.add_argument("--datasets", default=",".join(DEFAULT_DATASETS))
    ap.add_argument("--per-dataset", type=int, default=12)
    ap.add_argument("--model", default="", help="empty follows the app's own routing")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    datasets = [d.strip() for d in args.datasets.split(",") if d.strip()]
    rows = collect(args.backend_url, datasets, args.per_dataset, args.model)
    if not rows:
        print("ERROR: no answers collected", file=sys.stderr)
        return 1

    empty = sum(1 for r in rows if not r["answer"])
    no_context = sum(1 for r in rows if not r["context"])
    payload = {
        # The build that produced the answers. A label describes what this build
        # said, and a later build's answers are a different set (E5).
        "environment": capture_environment(args.backend_url, purpose="faithfulness-labels"),
        "collected": len(rows),
        "empty_answers": empty,
        "answers_without_context": no_context,
        "rows": rows,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(
        f"\n  {len(rows)} answers -> {args.out}"
        f"\n  {empty} empty, {no_context} with no retrieved context"
        f"\n  every label field is null: nothing here is labelled yet",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
