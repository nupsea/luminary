"""Calibrate the local judge panel against the labelled cards. Local only.

    MEM_CAP_GB=8 scripts/capped_run.sh uv run --directory backend python \
        <repo>/evals/card_quality/calibrate.py [--judge] [--run N]

The labels live in labels/, which is gitignored: DDIA ch.3 is copyrighted and its cards, passages
and the verdicts quoting them never leave this machine. Two sets:

- checker: the cards the 14B who-check scored, on the passage the 14B saw. Gate: the panel's
  judge must beat the 14B's wrong-person result on the same cards.
- labels: every source-checked card, on its source_passage, scored per error class.

Without --judge it only scores cached verdicts and never calls a model. A missing or refused
verdict is reported as such and never counts as a catch or a pass.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parents[1]) not in sys.path:
    sys.path.insert(0, str(HERE.parents[1]))

from evals.card_quality.judge_panel import (  # noqa: E402
    LABELS,
    PANEL,
    VERDICTS,
    cache_path,
    card_key,
    judge_all,
    load_cache,
)

# The 14B's result on the checker set (score_whocheck3): 5 of 9 wrong-person cards caught at 2 of
# 59 false flags. 6/9 at 2/59 beats it; 5/9 at 2/59 and 6/9 at 3/59 do not.
BASELINE_CAUGHT, BASELINE_FALSE_FLAGS = 5, 2
BASELINE_POSITIVES, BASELINE_NEGATIVES = 9, 59


def beats_baseline(caught: int, false_flags: int) -> bool:
    return caught > BASELINE_CAUGHT and false_flags <= BASELINE_FALSE_FLAGS


def _rows(name: str) -> list[dict]:
    return [json.loads(x) for x in (LABELS / name).read_text().splitlines() if x.strip()]


def checker_set() -> tuple[list[dict], dict[str, dict]]:
    cards, truth = [], {}
    for r in _rows("checker_59.jsonl"):
        cards.append({**_card(r, passage=r["evidence"]), "bucket": r["bucket"]})
        truth[r["card_id"]] = {"wrong_person": r["wrong_person"], "bucket": r["bucket"]}
    return cards, truth


def label_set() -> tuple[list[dict], dict[str, dict]]:
    """Claude's source checks are the truth: the rater's labels carry no correct "yes"."""
    rows = [r for r in _rows("labels.jsonl") if r["labeller"] == "source_check"]
    return [_card(r, passage=r["source_passage"]) for r in rows], {
        r["card_id"]: r["labels"] for r in rows
    }


def _card(row: dict, *, passage: str) -> dict:
    return {
        "card_id": row["card_id"],
        "doc": row["doc"],
        "chapter": row.get("chapter") or "",
        "question": row["question"],
        "answer": row["answer"],
        "passage": passage,
    }


def verdicts_for(cards: list[dict], run: int) -> dict[str, dict[str, dict | None]]:
    """{judge: {card_id: verdict or None}}."""
    out: dict[str, dict[str, dict | None]] = {}
    for judge in PANEL:
        cache = load_cache(cache_path(judge, run, VERDICTS))
        out[judge] = {c["card_id"]: (cache.get(card_key(c)) or {}).get("verdict") for c in cards}
    return out


def score_flag(truth: dict[str, bool | None], verdicts: dict[str, dict | None], field: str) -> dict:
    s = Counter()
    for card_id, label in truth.items():
        if label is None:
            continue
        got = (verdicts.get(card_id) or {}).get(field)
        side = "pos" if label else "neg"
        s[f"{side}_total"] += 1
        s[f"{side}_" + ("none" if got is None else "flagged" if got else "clear")] += 1
    return dict(s)


def score_correct(truth: dict[str, str | None], verdicts: dict[str, dict | None]) -> dict:
    """The two error directions apart: passing a wrong card is not the same failure as failing a
    right one."""
    grid = Counter()
    for card_id, label in truth.items():
        if label is not None:
            grid[(label, (verdicts.get(card_id) or {}).get("correct"))] += 1
    labelled = sum(grid.values())
    return {
        "labelled": labelled,
        "agree": sum(n for (t, g), n in grid.items() if t == g),
        "passed_wrong": grid[("no", "yes")],
        "failed_right": grid[("yes", "no")] + grid[("yes", "partial")],
        "no_verdict": sum(n for (_, g), n in grid.items() if g is None),
        "grid": {f"{t}->{g}": n for (t, g), n in sorted(grid.items(), key=str)},
    }


def report(run: int) -> None:
    cards, truth = checker_set()
    got = verdicts_for(cards, run)
    wp = {
        cid: t["wrong_person"] for cid, t in truth.items() if t["bucket"] in {"referent", "ok"}
    }
    if Counter(wp.values()) != {True: BASELINE_POSITIVES, False: BASELINE_NEGATIVES}:
        raise SystemExit(f"checker set is not the 14B's 9 + 59 cards: {Counter(wp.values())}")
    print(f"== checker set, run {run}: wrong_person on the 9 referent + 59 ok cards")
    print(f"   qwen2.5:14b (stored): caught {BASELINE_CAUGHT}/9, "
          f"false flags {BASELINE_FALSE_FLAGS}/59")
    for judge, verdicts in got.items():
        s = score_flag(wp, verdicts, "wrong_person")
        caught, flags = s.get("pos_flagged", 0), s.get("neg_flagged", 0)
        gate = f"  gate {'PASS' if beats_baseline(caught, flags) else 'fail'}"
        print(f"   {judge}: caught {caught}/9, false flags {flags}/59, "
              f"no verdict {s.get('pos_none', 0)}+{s.get('neg_none', 0)}{gate}")

    cards, truth = label_set()
    got = verdicts_for(cards, run)
    print(f"== label set, run {run}: {len(cards)} source-checked cards")
    correct = {c: t["correct"] for c, t in truth.items()}
    for judge, verdicts in got.items():
        print(f"   {judge}")
        print(f"      correct: {score_correct(correct, verdicts)}")
        for field in ("wrong_person", "truncated", "added_claim"):
            labelled = {c: t[field] for c, t in truth.items()}
            s = score_flag(labelled, verdicts, field)
            print(f"      {field}: {s or 'never labelled: unmeasured'}")


def judge(run: int, *, retry_refused: bool) -> None:
    cards = [c for build in (checker_set, label_set) for c in build()[0]]
    refuse_held_out(cards)
    unique = list({card_key(c): c for c in cards}.values())
    print(f"{len(unique)} distinct cards, run {run}", flush=True)
    for name in PANEL:
        judge_all(unique, name, run, VERDICTS, retry_refused=retry_refused)
        stop = ["ollama", "stop", name.split("/", 1)[1]]
        subprocess.run(stop, capture_output=True, check=False)  # noqa: S603, S607 -- PANEL tags


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--judge", action="store_true", help="ask the panel what is not cached")
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument(
        "--retry-refused", action="store_true", help="with --judge, re-ask refused cards"
    )
    args = parser.parse_args()
    if not LABELS.exists():
        raise SystemExit(f"no labels at {LABELS}: they are local only, copied in by hand")
    if args.judge:
        judge(args.run, retry_refused=args.retry_refused)
    report(args.run)


if __name__ == "__main__":
    main()
