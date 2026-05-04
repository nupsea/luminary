#!/usr/bin/env bash
# Smoke test for S216: summary correctness eval framework.
#
# No live backend required. Verifies golden schema, metric functions, summary
# history persistence, and run_summary_eval.py CLI help.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

test "$(wc -l < "$ROOT/evals/golden/summaries.jsonl")" -ge 9

HELP="$(cd "$ROOT/evals" && uv run --no-sync python run_summary_eval.py --help)"
grep -q -- "--mode" <<<"$HELP"
grep -q -- "--skip-judge" <<<"$HELP"

uv run --project "$ROOT/backend" --no-sync python - <<'PY'
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from evals.lib.loader import load_golden
from evals.lib.schemas import SummaryGoldenEntry
from evals.lib.scoring_history import append_history
from evals.lib.summary_metrics import (
    compute_conciseness_pct,
    compute_no_hallucination,
    compute_theme_coverage,
)

rows = load_golden("summaries", SummaryGoldenEntry)
assert len(rows) >= 9
assert {r["mode"] for r in rows} >= {"one_sentence", "executive", "detailed"}

summary = "Alice follows a rabbit into Wonderland and changes size."
assert compute_theme_coverage(summary, ["alice", "rabbit", "queen", "size|change"]) == 0.75
assert compute_no_hallucination(0, 5) == 1.0
assert compute_conciseness_pct("abcd", 8) == 0.5

with tempfile.TemporaryDirectory() as td:
    target = Path(td) / "scores.jsonl"
    append_history(
        "summaries",
        "judge",
        {"theme_coverage": 0.75, "no_hallucination": 1.0, "conciseness_pct": 0.5},
        True,
        eval_kind="summary",
        path=target,
    )
    row = json.loads(target.read_text().strip())
    assert row["eval_kind"] == "summary"
    assert row["theme_coverage"] == 0.75
    assert row["no_hallucination"] == 1.0
    assert row["conciseness_pct"] == 0.5

print("PASS: S216 -- summary goldens, metrics, history, and CLI wiring are green")
PY
