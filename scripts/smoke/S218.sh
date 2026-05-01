#!/usr/bin/env bash
# Smoke test for S218: intent routing eval.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

test "$(wc -l < "$ROOT/evals/golden/intents.jsonl")" -ge 50
HELP="$(cd "$ROOT/evals" && uv run --no-sync python run_intent_eval.py --help)"
grep -q -- "--assert-thresholds" <<<"$HELP"

uv run --project "$ROOT/backend" --no-sync python - <<'PY'
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from evals.lib.intent_metrics import compute_per_route_precision_recall, compute_routing_accuracy
from evals.lib.loader import load_golden
from evals.lib.schemas import IntentGoldenEntry
from evals.lib.scoring_history import append_history

rows = load_golden("intents", IntentGoldenEntry)
assert len(rows) >= 50
assert {"summary", "graph", "comparative", "search"} <= {r["expected_route"] for r in rows}
samples = [
    {"expected_route": "summary", "predicted_route": "summary"},
    {"expected_route": "search", "predicted_route": "search"},
    {"expected_route": "graph", "predicted_route": "search"},
]
assert compute_routing_accuracy(samples) == 2 / 3
assert "summary" in compute_per_route_precision_recall(samples)
with tempfile.TemporaryDirectory() as td:
    target = Path(td) / "scores.jsonl"
    append_history("intents", "classifier", {"routing_accuracy": 1.0}, True, eval_kind="intent", path=target)
    row = json.loads(target.read_text().strip())
    assert row["eval_kind"] == "intent"
    assert row["routing_accuracy"] == 1.0
print("PASS: S218 -- intent goldens, metrics, history, and CLI wiring are green")
PY
