"""Check the judges against human labels (E10).

Two numbers gate things in this repo without anything establishing they are
right: `citation_support_rate`, produced by an LLM judge scoring its own notion
of support, and `faithfulness`, an NLI score whose floor is `mean - 3sd` because
the observed distribution is unimodal and offers nowhere to put a bar.

This reads a labelled set and asks three questions of it:

1. **Does the citation judge agree with a human?** Reported as agreement plus the
   two error directions separately -- a judge that passes bad citations and one
   that rejects good ones are different failures with different consequences,
   and a single accuracy number hides which one you have.
2. **Does the faithfulness score separate grounded answers from ungrounded
   ones?** If the two label classes overlap, no threshold can tell them apart
   and any floor is a collapse detector, not a quality bar. That is a finding
   about the metric, not about the answers.
3. **Where would a bar go, if one can go anywhere?** Reported as the threshold
   maximising separation, with the errors it would still make.

Nothing here tunes anything. A threshold chosen to make a current run pass is
the shortcut this file exists to make unnecessary.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from evals.lib.citation_metrics import judge_citation  # noqa: E402


def _grounding_labelled(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("label_grounded") is not None]


def _citation_labelled(rows: list[dict]) -> list[dict]:
    """Rows with citation labels, which are not the same rows.

    Citation labels need the answer and the excerpt; a grounding label needs the
    whole retrieved context, which is a median 26k characters. Filtering the
    citation check by the grounding label silently threw away two thirds of the
    comparison.
    """
    return [
        r for r in rows
        if any(x is not None for x in (r.get("label_citation_supported") or []))
    ]


def validate_citation_judge(rows: list[dict], judge_model: str) -> dict:
    """The judge's verdict against the human label, per citation."""
    agree = 0
    judge_passed_bad = []   # judge said supported, human said not
    judge_failed_good = []  # judge said not supported, human said supported
    total = 0

    for row in rows:
        labels = row.get("label_citation_supported") or []
        for citation, label in zip(row.get("citations", []), labels, strict=False):
            if label is None:
                continue
            excerpt = (citation.get("excerpt") or "").strip()
            if not excerpt:
                continue
            total += 1
            try:
                verdict = judge_citation(row["answer"], excerpt, judge_model)
            except Exception as exc:  # noqa: BLE001
                print(f"  judge error: {type(exc).__name__}", file=sys.stderr)
                total -= 1
                continue
            # `partial` counts as supported for the pass/fail comparison: the
            # metric it feeds scores it 0.5, so a reader treating it as a pass is
            # reading the metric correctly.
            judged_supported = verdict in ("yes", "partial")
            if judged_supported == bool(label):
                agree += 1
            elif judged_supported:
                judge_passed_bad.append({"q": row["question"][:70], "excerpt": excerpt[:90]})
            else:
                judge_failed_good.append({"q": row["question"][:70], "excerpt": excerpt[:90]})

    return {
        "citations_compared": total,
        "agreement": (agree / total) if total else None,
        "passed_an_unsupported_citation": len(judge_passed_bad),
        "rejected_a_supported_citation": len(judge_failed_good),
        "examples_passed_bad": judge_passed_bad[:5],
        "examples_failed_good": judge_failed_good[:5],
    }


def separation(scores_by_label: dict[bool, list[float]]) -> dict:
    """Whether a threshold can tell the two label classes apart.

    Overlapping distributions mean no bar exists at any value, which is the
    honest answer and the one that keeps a floor from being quoted as a quality
    target.
    """
    grounded = sorted(scores_by_label.get(True) or [])
    ungrounded = sorted(scores_by_label.get(False) or [])
    if not grounded or not ungrounded:
        return {"separable": None, "reason": "one label class is empty"}

    best = {"threshold": None, "correct": -1}
    for candidate in sorted({*grounded, *ungrounded}):
        correct = sum(1 for s in grounded if s >= candidate) + sum(
            1 for s in ungrounded if s < candidate
        )
        if correct > best["correct"]:
            best = {"threshold": candidate, "correct": correct}

    total = len(grounded) + len(ungrounded)
    return {
        "grounded_n": len(grounded),
        "ungrounded_n": len(ungrounded),
        "grounded_mean": round(statistics.mean(grounded), 4),
        "ungrounded_mean": round(statistics.mean(ungrounded), 4),
        "grounded_range": [round(grounded[0], 4), round(grounded[-1], 4)],
        "ungrounded_range": [round(ungrounded[0], 4), round(ungrounded[-1], 4)],
        "overlaps": grounded[0] < ungrounded[-1],
        "best_threshold": round(best["threshold"], 4) if best["threshold"] is not None else None,
        "accuracy_at_best_threshold": round(best["correct"] / total, 4),
        "errors_at_best_threshold": total - best["correct"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--judge-model", default="ollama/qwen2.5:14b-instruct")
    ap.add_argument("--skip-citation-judge", action="store_true")
    args = ap.parse_args()

    payload = json.loads(Path(args.labels).read_text())
    rows = _grounding_labelled(payload["rows"])
    citation_rows = _citation_labelled(payload["rows"])
    if not rows and not citation_rows:
        print("ERROR: nothing in this file is labelled", file=sys.stderr)
        return 1

    print(f"\n{'=' * 62}")
    print(f"  Judge validation -- {len(rows)} labelled answers")
    print(f"  labelled by: {sorted({r.get('labeller') for r in rows})}")
    print(f"{'=' * 62}\n")

    grounded = sum(1 for r in rows if r["label_grounded"])
    print(f"  answers with a grounding label: {len(rows)} "
          f"({grounded} grounded, {len(rows) - grounded} not)")

    labels = [x for r in citation_rows for x in (r["label_citation_supported"] or [])
              if x is not None]
    print(f"  citations labelled: {len(labels)} "
          f"({sum(labels)} supported, {len(labels) - sum(labels)} not)")
    if labels:
        majority = max(sum(labels), len(labels) - sum(labels)) / len(labels)
        print(f"  a judge that answers the same way every time scores {majority:.4f} "
              f"-- agreement below this is worse than a constant")

    if not args.skip_citation_judge:
        print(f"\n  citation judge ({args.judge_model}):")
        result = validate_citation_judge(citation_rows, args.judge_model)
        for key in (
            "citations_compared",
            "agreement",
            "passed_an_unsupported_citation",
            "rejected_a_supported_citation",
        ):
            print(f"    {key:<34} {result[key]}")
        for example in result["examples_passed_bad"]:
            print(f"      passed a bad one: {example['excerpt']}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
