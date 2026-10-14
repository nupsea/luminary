"""Run the local judge panel over a card set, caching each judge's verdicts.

    MEM_CAP_GB=48 scripts/capped_run.sh uv run --directory backend python \
        ../evals/card_quality/judge_panel.py --cards cards.jsonl

A card row is {card_id, doc, chapter, question, answer, passage}. A verdict is cached under
(card hash, judge, PROMPT_VERSION), so a rerun only asks what it has not asked. `--run 2` keeps a
second, independent pass for the determinism check. Verdicts quote the passage, so they live in
the gitignored labels/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parents[1]) not in sys.path:
    sys.path.insert(0, str(HERE.parents[1]))

from evals.card_quality.card_judge import PROMPT_VERSION, JudgeRefused, judge_card  # noqa: E402

# One judge: a three-way majority with gpt-oss:20b and qwen3.6:27b caught fewer than gemma alone.
PANEL = ("ollama/gemma4:31b-it-q8_0",)
LABELS = HERE / "labels"
VERDICTS = LABELS / "verdicts"


def held_out() -> set[tuple[str, str]]:
    rows = (HERE / "HELD_OUT").read_text().splitlines()
    return {
        (_phrase(doc), _phrase(chapter))
        for doc, chapter in (row.split("\t") for row in rows if row.strip() and row[0] != "#")
    }


def _phrase(text: str) -> str:
    """Lower-case words between spaces, so "book ix" is found in "BOOK IX ULYSSES" and not
    in "BOOK XIX"."""
    return " " + " ".join(re.findall(r"[a-z0-9]+", text.lower())) + " "


def refuse_held_out(cards: list[dict]) -> None:
    banned = held_out()
    hits = [
        c["card_id"]
        for c in cards
        if any(d in _phrase(c["doc"]) and ch in _phrase(c["chapter"]) for d, ch in banned)
    ]
    if hits:
        raise SystemExit(f"{len(hits)} held-out cards in the set (step 4's chapters): {hits[:5]}")


def card_key(card: dict) -> str:
    body = "\x1f".join(card[k] for k in ("question", "answer", "passage"))
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def cache_path(judge: str, run: int, verdicts: Path = VERDICTS) -> Path:
    name = judge.split("/", 1)[-1].replace(":", "_")
    return verdicts / f"{name}.run{run}.jsonl"


def load_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    rows = (json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return {r["key"]: r for r in rows if r["prompt_version"] == PROMPT_VERSION}


def judge_all(
    cards: list[dict], judge: str, run: int, verdicts: Path = VERDICTS, *, retry_refused=False
) -> None:
    """Ask what is not cached. retry_refused re-asks refusals after a check changes; the new
    row is appended and load_cache keeps the last row per card, so nothing is deleted."""
    path = cache_path(judge, run, verdicts)
    cached = load_cache(path)
    todo = [
        c
        for c in cards
        if card_key(c) not in cached or (retry_refused and cached[card_key(c)].get("refused"))
    ]
    print(f"{judge} run {run}: {len(cached)} cached, {len(todo)} to ask", file=sys.stderr)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as out:
        for card in todo:
            started = time.monotonic()
            row = {
                "key": card_key(card),
                "card_id": card["card_id"],
                "judge": judge,
                "prompt_version": PROMPT_VERSION,
            }
            try:
                q, a, p = card["question"], card["answer"], card["passage"]
                row["verdict"] = judge_card(q, a, p, judge)
            except JudgeRefused as exc:
                row["verdict"], row["refused"], row["raw"] = None, str(exc), exc.raw
            except Exception as exc:  # noqa: BLE001 -- a failed call is a missing verdict
                row["verdict"], row["error"] = None, f"{type(exc).__name__}: {exc}"
            row["seconds"] = round(time.monotonic() - started, 2)
            out.write(json.dumps(row) + "\n")
            out.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cards", type=Path, required=True)
    parser.add_argument("--judges", default=",".join(PANEL))
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--verdicts", type=Path, default=VERDICTS)
    args = parser.parse_args()
    # No refuse_held_out: the panel is the instrument that judges step 4's cards.
    cards = [json.loads(line) for line in args.cards.read_text().splitlines() if line.strip()]
    for judge in args.judges.split(","):
        judge_all(cards, judge.strip(), args.run, args.verdicts)


if __name__ == "__main__":
    main()
