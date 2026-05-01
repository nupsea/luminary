#!/usr/bin/env bash
# Smoke test for S217: flashcard correctness eval framework.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

test "$(wc -l < "$ROOT/evals/golden/flashcards.jsonl")" -ge 6

HELP="$(cd "$ROOT/evals" && uv run --no-sync python run_flashcard_eval.py --help)"
grep -q -- "--judge-model" <<<"$HELP"

uv run --project "$ROOT/backend" --no-sync python - <<'PY'
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from evals.lib.flashcard_metrics import compute_atomicity, compute_clarity_avg, compute_factuality
from evals.lib.loader import load_golden
from evals.lib.schemas import FlashcardGoldenEntry
from evals.lib.scoring_history import append_history

rows = load_golden("flashcards", FlashcardGoldenEntry)
assert len(rows) >= 6
assert compute_factuality(["yes", "yes", "partial", "no"]) == 0.625
assert compute_atomicity([True, False, True]) == 2 / 3
assert compute_clarity_avg([5, 4, 3]) == 4.0

with tempfile.TemporaryDirectory() as td:
    target = Path(td) / "scores.jsonl"
    append_history(
        "flashcards",
        "judge",
        {"factuality": 0.625, "atomicity": 0.8, "clarity_avg": 4.0},
        True,
        eval_kind="flashcard",
        path=target,
    )
    row = json.loads(target.read_text().strip())
    assert row["eval_kind"] == "flashcard"
    assert row["factuality"] == 0.625
    assert row["atomicity"] == 0.8
    assert row["clarity_avg"] == 4.0

print("PASS: S217 -- flashcard goldens, metrics, history, and CLI wiring are green")
PY
