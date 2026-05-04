#!/usr/bin/env bash
# Smoke test for S223: cross-domain golden datasets.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

test -f "$ROOT/DATA/papers/art_of_unix.txt"
test -f "$ROOT/DATA/conversations/engineering_sync.txt"
test -f "$ROOT/DATA/notes/ml_notes.txt"
test -f "$ROOT/DATA/code/embedder.py"

uv run --project "$ROOT/backend" --no-sync python -m evals.lib.audit

uv run --project "$ROOT/backend" --no-sync pytest \
  "$ROOT/backend/tests/test_cross_domain_goldens.py" \
  "$ROOT/backend/tests/test_eval_metrics.py" -k 'cross_domain'

uv run --project "$ROOT/backend" --no-sync ruff check \
  "$ROOT/backend/tests/test_cross_domain_goldens.py" \
  "$ROOT/backend/tests/test_eval_metrics.py" \
  "$ROOT/evals/run_eval.py"

echo "PASS: S223 -- cross-domain fixtures, goldens, audit, and threshold config are green"
