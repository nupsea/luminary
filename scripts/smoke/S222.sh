#!/usr/bin/env bash
# Smoke test for S222: retrieval strategy ablation eval.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

HELP="$(cd "$ROOT/evals" && uv run --no-sync python run_eval.py --help)"
grep -q -- "--ablation" <<<"$HELP"
grep -q 'strategy: RetrievalStrategy = "rrf"' "$ROOT/backend/app/services/retriever.py"
grep -q 'strategy: str = Query' "$ROOT/backend/app/routers/search.py"
grep -q 'ablation_metrics' "$ROOT/backend/app/routers/monitoring.py"

uv run --project "$ROOT/backend" --no-sync pytest \
  "$ROOT/backend/tests/test_ablation_eval.py" \
  "$ROOT/backend/tests/test_monitoring.py" -k 'ablation or store_eval_run_creates_row'

uv run --project "$ROOT/backend" --no-sync ruff check \
  "$ROOT/backend/app/services/retriever.py" \
  "$ROOT/backend/app/routers/search.py" \
  "$ROOT/backend/app/routers/monitoring.py" \
  "$ROOT/backend/tests/test_ablation_eval.py" \
  "$ROOT/evals/run_eval.py" \
  "$ROOT/evals/lib/scoring_history.py" \
  "$ROOT/evals/lib/store.py"

echo "PASS: S222 -- retrieval strategy ablation wiring and tests are green"
