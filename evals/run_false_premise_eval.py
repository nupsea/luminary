"""False-premise eval (#158): a question built on something the document contradicts.

Every row's document holds the passage that corrects the premise. A good answer
says so and cites it. A bare not_found tells the user the document does not cover
the topic, which is false; echoing the premise is worse.

  corrected   not declined; the answer names a correction term, and so does a
              passage one of its citations points at
  uncited     names a correction term but no citation carries one
  declined    not_found, or an honest-decline error code
  other       an answer that never states the correction (it echoed the premise)
  empty       the call failed

Usage:
    cd evals
    uv run python run_false_premise_eval.py --backend-url http://localhost:7820 \
        --model ollama/qwen3.5:4b [--assert-thresholds]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib.environment import capture as capture_environment  # noqa: E402
from evals.lib.manifest import (  # noqa: E402
    ensure_ingested,
    load_manifest,
    require_backend,
    resolve_backend_base,
)
from evals.lib.scoring_history import append_history  # noqa: E402
from evals.run_refusal_eval import (  # noqa: E402
    _HONEST_DECLINE_ERROR_CODES,
    load_dataset,
    post_qa,
)

DATASET = "false_premise"
# Bracketed by two arms on one library copy, qwen3.5:4b, 2026-10-01: master before the
# premise rule scored 0.43 and 0.14, the rule 0.57 on four runs. 7 rows, so one row is
# 0.14 and the floor sits on the one-row step between them. The three novel rows fail on
# both arms: the model does not read the correction out of narrative (#158 stays open).
DEFAULT_THRESHOLD = 0.50


def classify(resp: dict, correction: list[str]) -> str:
    if not resp:
        return "empty"
    error = resp.get("error")
    if resp.get("not_found") or error in _HONEST_DECLINE_ERROR_CODES:
        return "declined"
    if error:
        return "empty"
    answer = (resp.get("answer") or "").lower()
    if not answer.strip():
        return "empty"
    if not any(term in answer for term in correction):
        return "other"
    passages = [_cited_passage(c, resp.get("context_chunks") or []) for c in resp.get("citations") or []]
    if any(term in passage for passage in passages for term in correction):
        return "corrected"
    return "uncited"


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _cited_passage(citation: dict, context_chunks: list[str]) -> str:
    """The whole passage a citation points at. Its excerpt is a window cut around the
    answer's wording, so the correcting sentence can sit just outside it."""
    excerpt = _norm(citation.get("excerpt") or "").removeprefix("... ").removesuffix("...")
    for chunk in context_chunks:
        if excerpt and excerpt in _norm(chunk):
            return _norm(chunk)
    return excerpt


def main() -> None:
    ap = argparse.ArgumentParser(description="False-premise eval (#158).")
    ap.add_argument("--backend-url", default="http://localhost:7820")
    ap.add_argument("--model", default=None)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--assert-thresholds", action="store_true")
    args = ap.parse_args()

    require_backend(args.backend_url)
    backend_url = resolve_backend_base(args.backend_url)
    rows = load_dataset(DATASET)
    manifest = load_manifest()
    doc_ids = {
        src: ensure_ingested(backend_url, src, manifest)
        for src in {r["source_file"] for r in rows}
    }

    counts = dict.fromkeys(("corrected", "uncited", "declined", "other", "empty"), 0)
    for i, row in enumerate(rows, 1):
        resp = post_qa(backend_url, row["question"], args.model, doc_ids[row["source_file"]])
        outcome = classify(resp, [t.lower() for t in row["correction"]])
        counts[outcome] += 1
        answer = " ".join((resp.get("answer") or "").split())[:160]
        print(f"  [{i}/{len(rows)}] {outcome:9} {row['question'][:60]}\n             {answer}")

    total = len(rows)
    correction_rate = counts["corrected"] / total
    print("\n" + "=" * 56)
    print(f"  False-premise eval -- model={args.model or 'default'}")
    for k, v in counts.items():
        print(f"  {k:15} {v}/{total}")
    print(f"  correction_rate {correction_rate:.4f}")
    print("=" * 56)

    append_history(
        DATASET,
        args.model or "default",
        {"correction_rate": correction_rate, **counts, "total": total},
        passed=correction_rate >= args.threshold and counts["empty"] == 0,
        eval_kind="false_premise",
        environment=capture_environment(backend_url, dataset=DATASET, model=args.model),
    )
    if args.assert_thresholds:
        if counts["empty"]:
            sys.exit(f"FAIL: {counts['empty']} call(s) failed outright")
        if correction_rate < args.threshold:
            sys.exit(f"FAIL: correction_rate {correction_rate:.4f} < {args.threshold:.4f}")
        print("PASS")


if __name__ == "__main__":
    main()
