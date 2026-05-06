#!/usr/bin/env bash
# Smoke test for S213: unified eval harness + Pydantic golden schema.
#
# Verifies (no live backend required):
#   1. evals.lib package imports cleanly and exposes the documented public API
#      (RetrievalGoldenEntry, SummaryGoldenEntry, FlashcardGoldenEntry,
#      IntentGoldenEntry, load_golden, append_history, store_results,
#      compute_hit_rate_5, compute_mrr, RetrievalEval/GenerationEval/ClassifierEval).
#   2. evals.run_eval still re-exports GoldenEntry / compute_hit_rate_5 / compute_mrr
#      (backwards-compat for audit_golden.py and test_eval_metrics.py).
#   3. python -m evals.lib.audit exits 0 and prints PASS for every golden file.
#   4. append_history writes an entry whose eval_kind defaults to 'retrieval'.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

uv run --project "$ROOT/backend" --no-sync python - <<'PY'
import json
import sys
import tempfile
from pathlib import Path

# Public lib import
from evals.lib import (
    ClassifierEval,
    FlashcardGoldenEntry,
    GenerationEval,
    GoldenEntry,
    IntentGoldenEntry,
    RetrievalEval,
    RetrievalGoldenEntry,
    SummaryGoldenEntry,
    append_history,
    compute_hit_rate_5,
    compute_mrr,
    load_golden,
    store_results,
)

# 1. Schema coercion (S226 invariant preserved)
e = RetrievalGoldenEntry(question="q", ground_truth_answer="a", context_hint="hint")
assert e.context_hint == ["hint"], f"expected ['hint'], got {e.context_hint!r}"
e2 = RetrievalGoldenEntry(question="q", ground_truth_answer="a", context_hint=["a", "b"])
assert e2.context_hint == ["a", "b"]

# 2. Backwards-compat: run_eval still exposes the legacy names
sys.path.insert(0, str(Path("evals").resolve()))
from run_eval import GoldenEntry as _legacy_entry
from run_eval import compute_hit_rate_5 as _legacy_hr
from run_eval import compute_mrr as _legacy_mrr

assert _legacy_entry is RetrievalGoldenEntry
samples = [{"context_hint": ["x"], "contexts": ["x is here"], "ground_truths": ["g"]}]
assert _legacy_hr(samples) == 1.0
assert _legacy_mrr(samples) == 1.0

# 3. Eval runner base classes are concrete
metrics = RetrievalEval().run(samples)
assert metrics["hit_rate_5"] == 1.0 and metrics["mrr"] == 1.0
RetrievalEval().assert_thresholds(metrics, {"hit_rate_5": 0.5, "mrr": 0.5})

# 4. append_history defaults eval_kind='retrieval'
with tempfile.TemporaryDirectory() as td:
    target = Path(td) / "scores.jsonl"
    append_history("ds", "no-llm", {"hit_rate_5": 0.6, "mrr": 0.4}, True, path=target)
    rows = [json.loads(line) for line in target.read_text().splitlines() if line]
    assert rows[0]["eval_kind"] == "retrieval", rows[0]

# 5. python -m evals.lib.audit exits 0 against the real golden directory
import subprocess
result = subprocess.run(
    [sys.executable, "-m", "evals.lib.audit"],
    capture_output=True,
    text=True,
)
assert result.returncode == 0, f"audit exited {result.returncode}: {result.stdout}\n{result.stderr}"
assert "FAIL" not in result.stdout, f"audit reported FAIL: {result.stdout}"

print("PASS: S213 -- evals.lib package + run_eval backwards-compat + audit CLI all green")
PY
