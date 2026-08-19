"""Does teach-back scoring order explanations correctly?

Teach-back has never been measured. The obvious harness -- a golden of
explanations with expected scores -- needs someone to label what each explanation
deserves, and a scorer validated against labels one person wrote is a scorer
validated against one person.

The property that actually matters needs no labels: **ordering**. A correct
explanation must score above an incomplete one, an incomplete one above a wrong
one, and anything above an explanation of something else entirely. Input quality
can be constructed from the card itself, so the expected ranking is known by
construction rather than judged:

  correct     the card's own answer -- it is the reference, so it must score high
  incomplete  the answer's first clause only, which drops what follows
  wrong       the answer with its claim negated
  unrelated   another card's answer

What this measures is the scorer, not the model's knowledge. It is deterministic
apart from the model, re-runs against any model, and fails loudly when the middle
of the range is uncalibrated -- which is what an ad-hoc probe suggested: a vague
explanation scored 10 against an outright wrong one at 15, where the prompt's own
bands put "partly right" at 40-69.

First run, 2026-08-18, 10 cases against `qwen3.5:4b`:

    cases_scored 3, cases_incomplete 7   ordering_accuracy 1.0 (0 inversions / 9 pairs)
    unrelated 0.00, wrong 36.33, incomplete 73.33, correct 93.33
    correct_minus_wrong 57.0, no overlap

Two things that number is not. **Seven of ten cases were discarded** because the
evaluator returned unparseable JSON on at least one arm -- 11 failures in 40
calls, surviving its own two retries -- so the three that scored are the three
where the model happened to answer cleanly four times running, which is a
selection effect and not a random sample.

And the **`incomplete` arm is a gentler degradation than the case that failed
before**. An ad-hoc probe scored a vague-but-not-wrong explanation at 10 against
an outright wrong one at 15 -- an inversion. This harness's `incomplete` is the
answer's own first clause, which is much closer to correct than a vague sentence
is. A `vague` arm needs a paraphrase rather than a substring, so it cannot be
constructed the way these four are, and it is exactly where the scorer is known
to misbehave.

Usage::

    python evals/run_teachback_eval.py --limit 12 --assert-thresholds
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sqlite3
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402

from evals.lib.environment import capture as capture_environment  # noqa: E402
from evals.lib.scoring_history import append_history  # noqa: E402

# Ordered worst to best. The names are the harness's vocabulary, never the
# model's -- nothing about the construction reaches the prompt.
QUALITIES = ("unrelated", "wrong", "incomplete", "correct")

TEACHBACK_TIMEOUT = 300.0

_NEGATIONS = (
    (r"\bis\b", "is not"),
    (r"\bare\b", "are not"),
    (r"\bcan\b", "cannot"),
    (r"\bdoes\b", "does not"),
    (r"\bwill\b", "will not"),
    (r"\bhas\b", "does not have"),
    (r"\bincreases\b", "decreases"),
    (r"\bdecreases\b", "increases"),
    (r"\ballows\b", "prevents"),
    (r"\bprevents\b", "allows"),
)


def negate(answer: str) -> str | None:
    """The answer with its claim reversed, or None when nothing can be reversed.

    Returning None rather than a mangled string matters: a "wrong" explanation
    that is merely ungrammatical tests the scorer's tolerance for noise, not its
    grasp of the claim.
    """
    for pattern, replacement in _NEGATIONS:
        if re.search(pattern, answer):
            return re.sub(pattern, replacement, answer, count=1)
    return None


def first_clause(answer: str) -> str | None:
    """The opening clause alone -- true as far as it goes, and missing the rest."""
    parts = re.split(r",|;| because | so that | which ", answer, maxsplit=1)
    head = parts[0].strip().rstrip(".")
    if len(head) < 20 or len(head) >= len(answer.strip().rstrip(".")) - 5:
        return None  # nothing was actually dropped
    return head + "."


def build_cases(db_path: str, limit: int) -> list[dict]:
    """One card, four explanations of known relative quality."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT id, question, answer FROM flashcards "
        "WHERE grounding = 'verified' AND LENGTH(answer) > 60 "
        "ORDER BY id LIMIT ?",
        (limit * 3,),
    ).fetchall()

    cases = []
    for i, (card_id, _question, answer) in enumerate(rows):
        head, negated = first_clause(answer), negate(answer)
        if head is None or negated is None:
            continue  # this card cannot carry all four arms; skip rather than fake one
        other = rows[(i + len(rows) // 2) % len(rows)][2]
        if other == answer:
            continue
        cases.append({
            "flashcard_id": card_id,
            "explanations": {
                "correct": answer,
                "incomplete": head,
                "wrong": negated,
                "unrelated": other,
            },
        })
        if len(cases) >= limit:
            break
    return cases


def score(backend_url: str, flashcard_id: str, explanation: str) -> int | None:
    try:
        resp = httpx.post(
            f"{backend_url}/study/teachback",
            json={"flashcard_id": flashcard_id, "user_explanation": explanation},
            timeout=TEACHBACK_TIMEOUT,
        )
        resp.raise_for_status()
        value = resp.json().get("score")
        return int(value) if value is not None else None
    except httpx.HTTPStatusError as exc:
        # The status and body, not just the exception name: a run where every arm
        # failed reported "HTTPStatusError" eight times and said nothing about
        # why, which makes an uncomputed metric indistinguishable from a broken
        # harness.
        body = exc.response.text[:160].replace("\n", " ")
        print(f"    scoring failed: HTTP {exc.response.status_code} {body}", file=sys.stderr)
        return None
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        print(f"    scoring failed: {type(exc).__name__}: {str(exc)[:120]}", file=sys.stderr)
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend-url", default="http://localhost:7820")
    ap.add_argument("--db", default=str(REPO_ROOT / ".luminary" / "luminary.db"))
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--assert-thresholds", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    cases = build_cases(args.db, args.limit)
    if not cases:
        print("ERROR: no card could carry all four arms", file=sys.stderr)
        return 1

    scored: list[dict] = []
    for n, case in enumerate(cases, 1):
        result = {"flashcard_id": case["flashcard_id"], "scores": {}}
        for quality in QUALITIES:
            t0 = time.time()
            value = score(args.backend_url, case["flashcard_id"], case["explanations"][quality])
            result["scores"][quality] = value
            print(f"  [{n}/{len(cases)}] {quality:<11} {value}  ({time.time() - t0:.1f}s)",
                  file=sys.stderr)
        scored.append(result)

    # A case is only usable if every arm scored: a missing arm cannot be ordered,
    # and treating it as 0 would manufacture an ordering that was never measured.
    usable = [r for r in scored if all(v is not None for v in r["scores"].values())]
    inversions: list[str] = []
    for r in usable:
        s = r["scores"]
        for lower, higher in itertools.pairwise(QUALITIES):
            if s[lower] > s[higher]:
                inversions.append(
                    f"{r['flashcard_id'][:8]}: {lower} {s[lower]} > {higher} {s[higher]}"
                )

    pairs = len(usable) * (len(QUALITIES) - 1)
    metrics: dict[str, object] = {
        "cases": len(cases),
        "cases_scored": len(usable),
        "cases_incomplete": len(scored) - len(usable),
        "ordered_pairs": pairs,
        "inversions": len(inversions),
        # The headline: how often the scorer ranks a better explanation higher.
        "ordering_accuracy": round((pairs - len(inversions)) / pairs, 4) if pairs else None,
    }
    for quality in QUALITIES:
        values = [r["scores"][quality] for r in usable]
        if values:
            metrics[f"mean_{quality}"] = round(statistics.mean(values), 2)
    if usable:
        # Separation is what a gate would rest on: if correct and wrong overlap,
        # no score threshold distinguishes a good explanation from a bad one.
        correct = [r["scores"]["correct"] for r in usable]
        wrong = [r["scores"]["wrong"] for r in usable]
        metrics["correct_minus_wrong"] = round(
            statistics.mean(correct) - statistics.mean(wrong), 2
        )
        metrics["correct_wrong_overlap"] = min(correct) <= max(wrong)

    print(f"\n{'=' * 58}\n  Teach-back ordering\n{'=' * 58}")
    for key, value in metrics.items():
        print(f"  {key:<24} {value}")
    for line in inversions[:10]:
        print(f"    inversion: {line}")

    environment = capture_environment(args.backend_url, eval_kind="teachback")
    passed = not inversions
    append_history("teachback", environment.get("chat_model", "?"), metrics, passed,
                   eval_kind="teachback", environment=environment)
    if args.out:
        Path(args.out).write_text(json.dumps({"metrics": metrics, "cases": scored}, indent=2))

    if args.assert_thresholds and inversions:
        print(f"\nQUALITY GATE FAILED: {len(inversions)} ordering inversion(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
