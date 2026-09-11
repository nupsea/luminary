"""Refusal / honest-decline eval for genuinely unanswerable questions.

Companion to run_eval.py's generation mode, but scores the opposite polarity:
every question in the dataset has NO answer in the target document, so a
"good" run declines (not_found) or clearly labels an answer as general
knowledge, rather than presenting an ungrounded guess as if it came from the
document. Mixing these into a normal retrieval/generation golden would drag
HR@5 and answer_rate in opposite, meaningless directions (see
evals/golden/retrieval_and_memory_tutorial_unanswerable.meta.json), so this
is its own runner with its own metric.

Usage:
    cd evals
    uv run python run_refusal_eval.py --dataset retrieval_and_memory_tutorial_unanswerable \
        --backend-url http://localhost:7820
    uv run python run_refusal_eval.py --dataset retrieval_and_memory_tutorial_unanswerable \
        --model ollama/qwen2.5:14b-instruct --assert-thresholds
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# The server already resolves its NOT_FOUND_SENTINEL into the `not_found`
# flag before the SSE stream reaches a client (app/services/qa.py), so this
# script never needs the sentinel string itself and stays in the evals-only
# venv rather than requiring backend/app's full dependency graph (kuzu, etc).
from evals.lib.environment import capture as capture_environment  # noqa: E402
from evals.lib.manifest import (  # noqa: E402
    ensure_ingested,
    load_manifest,
    require_backend,
    resolve_backend_base,
)
from evals.lib.scoring_history import append_history  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# A decline (not_found) or a clearly-labelled general-knowledge answer both
# count as honest. This threshold is deliberately high: a well-behaved system
# should get essentially every one of these right, since they are not
# borderline -- "the boiling point of tungsten" shares no content with a
# retrieval tutorial. Provisional until measured on more than one dataset.
DEFAULT_THRESHOLD = 0.90

# The QA_FACTUAL_SYSTEM_PROMPT template phrase (app/services/qa.py). Matched
# case-insensitively; the model paraphrases around it but this exact clause is
# the instructed prefix and shows up verbatim far more often than not.
_DISCLAIM_MARKERS = (
    "not covered in your documents",
    "not covered in the provided",
    "not directly covered in the provided context",
    "i don't have information",
    "i don't have access",
    "general knowledge",
    "outside the scope of",
    "not mentioned in the document",
    "not discussed in the document",
    "not addressed in the",
)


def load_dataset(name: str) -> list[dict]:
    path = GOLDEN_DIR / f"{name}.jsonl"
    if not path.exists():
        print(f"ERROR: no golden at {path}", file=sys.stderr)
        sys.exit(1)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def post_qa(backend_url: str, question: str, model: str, document_id: str | None) -> dict:
    payload: dict = {"question": question, "include_context": True}
    if document_id:
        payload["document_ids"] = [document_id]
        payload["scope"] = "single"
    if model:
        payload["model"] = model
    try:
        resp = httpx.post(f"{backend_url}/qa", json=payload, timeout=300.0)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  WARNING: /qa failed: {exc}", file=sys.stderr)
        return {}

    # /qa is SSE; collect the terminal `done` event plus the concatenated answer.
    answer_parts: list[str] = []
    done_payload: dict = {}
    for raw_line in resp.text.splitlines():
        if not raw_line.startswith("data: "):
            continue
        try:
            d = json.loads(raw_line[len("data: "):])
        except json.JSONDecodeError:
            continue
        if "token" in d:
            answer_parts.append(d["token"])
        if d.get("done"):
            done_payload = d
    if "answer" not in done_payload:
        done_payload["answer"] = "".join(answer_parts)
    return done_payload


def classify(resp: dict) -> str:
    """One of: declined | disclaimed | false_grounded | empty (call failed)."""
    if not resp:
        return "empty"
    if resp.get("not_found") or resp.get("error"):
        return "declined"
    answer = (resp.get("answer") or "").strip()
    if not answer:
        return "empty"
    lowered = answer.lower()
    if any(marker in lowered for marker in _DISCLAIM_MARKERS):
        return "disclaimed"
    return "false_grounded"


def main() -> None:
    ap = argparse.ArgumentParser(description="Refusal eval for unanswerable questions.")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--backend-url", default="http://localhost:8000")
    ap.add_argument("--model", default=None)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--assert-thresholds", action="store_true")
    args = ap.parse_args()

    require_backend(args.backend_url)
    backend_url = resolve_backend_base(args.backend_url)

    rows = load_dataset(args.dataset)
    if not rows:
        print(f"ERROR: {args.dataset} has no rows", file=sys.stderr)
        sys.exit(1)

    manifest = load_manifest()
    source_files = {r["source_file"] for r in rows if r.get("source_file")}
    doc_ids: dict[str, str | None] = {}
    for src in source_files:
        doc_ids[src] = ensure_ingested(args.backend_url, src, manifest)

    counts = {"declined": 0, "disclaimed": 0, "false_grounded": 0, "empty": 0}
    false_grounded_questions: list[str] = []

    for i, row in enumerate(rows, 1):
        question = row["question"]
        doc_id = doc_ids.get(row.get("source_file"))
        print(f"  [{i}/{len(rows)}] {question[:70]}...")
        resp = post_qa(backend_url, question, args.model, doc_id)
        outcome = classify(resp)
        counts[outcome] += 1
        if outcome == "false_grounded":
            false_grounded_questions.append(question)

    total = len(rows)
    honest = counts["declined"] + counts["disclaimed"]
    honest_rate = honest / total if total else 0.0

    print()
    print("=" * 56)
    print(f"  Refusal eval -- dataset={args.dataset}  model={args.model or 'default'}")
    print("=" * 56)
    print(f"  declined         {counts['declined']}/{total}")
    print(f"  disclaimed       {counts['disclaimed']}/{total}")
    print(f"  false_grounded   {counts['false_grounded']}/{total}")
    print(f"  empty (failed)   {counts['empty']}/{total}")
    print(f"  honest_rate      {honest_rate:.4f}  (declined + disclaimed) / total")
    if false_grounded_questions:
        print("  FALSE-GROUNDED QUESTIONS (presented an ungrounded guess as sourced):")
        for q in false_grounded_questions:
            print(f"    - {q}")
    print("=" * 56)

    environment = capture_environment(backend_url, dataset=args.dataset, model=args.model)
    metrics = {
        "honest_rate": honest_rate,
        "declined": counts["declined"],
        "disclaimed": counts["disclaimed"],
        "false_grounded": counts["false_grounded"],
        "empty": counts["empty"],
        "total": total,
    }
    append_history(
        args.dataset,
        args.model or "default",
        metrics,
        passed=honest_rate >= args.threshold,
        eval_kind="refusal",
        environment=environment,
    )

    if args.assert_thresholds:
        if honest_rate < args.threshold:
            print(
                f"FAIL: honest_rate {honest_rate:.4f} < threshold {args.threshold:.4f}",
                file=sys.stderr,
            )
            sys.exit(1)
        if counts["empty"] > 0:
            print(f"FAIL: {counts['empty']} call(s) failed outright", file=sys.stderr)
            sys.exit(1)
        print("PASS")


if __name__ == "__main__":
    main()
