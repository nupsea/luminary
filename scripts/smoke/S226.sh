#!/usr/bin/env bash
# Smoke test for S226: multi-hint golden schema (context_hint accepts list[str]).
#
# Verifies:
#   1. evals/run_eval.py exposes GoldenEntry with the new validator
#      (str -> [str] coercion; empty list rejected).
#   2. compute_hit_rate_5 / compute_mrr count a sample as a hit if ANY
#      hint alternate matches any top-K chunk.
#   3. The two book datasets curated in this story (book_time_machine and
#      book_odyssey) each contain >= 5 multi-hint entries and load cleanly.
#   4. Existing string-form goldens (book_alice) continue to load.
#
# This is a pure-Python smoke check -- it does NOT require a running backend.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/evals"

uv run --project "$ROOT/backend" --no-sync python - <<'PY'
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from pydantic import ValidationError
from run_eval import GoldenEntry, compute_hit_rate_5, compute_mrr, load_golden


# 1a. str hint coerces to single-element list.
e = GoldenEntry(question="q", ground_truth_answer="a", context_hint="hint")
assert e.context_hint == ["hint"], f"unexpected: {e.context_hint!r}"

# 1b. list[str] preserved.
e = GoldenEntry(question="q", ground_truth_answer="a", context_hint=["a", "b"])
assert e.context_hint == ["a", "b"]

# 1c. empty list rejected.
try:
    GoldenEntry(question="q", ground_truth_answer="a", context_hint=[])
except ValidationError:
    pass
else:
    print("FAIL: empty list should have raised", file=sys.stderr)
    sys.exit(1)

# 2. metrics with multi-hint -- ANY-match semantics.
samples = [
    {
        "question": "q",
        "context_hint": ["needle-A", "needle-B"],
        "contexts": ["chunk1 has needle-B in it"],
        "ground_truths": ["GT"],
    }
]
assert compute_hit_rate_5(samples) == 1.0
assert compute_mrr(samples) == 1.0

# 3. curated datasets load and have >=5 multi-hint entries each.
for ds, min_multi in (("book_time_machine", 5), ("book_odyssey", 5)):
    rows = load_golden(ds)
    multi = sum(1 for r in rows if len(r.get("context_hint", [])) > 1)
    assert multi >= min_multi, f"{ds}: expected >={min_multi} multi-hint, got {multi}"
    print(f"  {ds}: {len(rows)} rows, {multi} multi-hint")

# 4. existing string-form datasets still load.
rows_alice = load_golden("book_alice")
assert len(rows_alice) > 0
for r in rows_alice:
    assert isinstance(r["context_hint"], list)
print(f"  book_alice: {len(rows_alice)} rows (all coerced to list-form)")

print("PASS: S226 -- multi-hint golden schema accepted by load_golden + metrics")
PY
