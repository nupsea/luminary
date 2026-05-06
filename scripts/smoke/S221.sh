#!/usr/bin/env bash
# Smoke test for S221: eval regression detection and Monitoring trends panel.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

test -f "$ROOT/backend/app/services/eval_regression_service.py"
test -f "$ROOT/frontend/src/components/EvalTrendsPanel.tsx"
grep -q '/evals/regressions' "$ROOT/backend/app/routers/monitoring.py"
grep -q 'EvalTrendsPanel' "$ROOT/frontend/src/pages/Monitoring.tsx"

uv run --project "$ROOT/backend" --no-sync pytest \
  "$ROOT/backend/tests/test_monitoring.py" -k 'regressions or eval_regressions'

uv run --project "$ROOT/backend" --no-sync ruff check \
  "$ROOT/backend/app/services/eval_regression_service.py" \
  "$ROOT/backend/app/routers/monitoring.py" \
  "$ROOT/backend/tests/test_monitoring.py"

(cd "$ROOT/frontend" && npx tsc --noEmit -p tsconfig.app.json)

echo "PASS: S221 -- regression endpoint, detection tests, and Monitoring trends panel are green"
