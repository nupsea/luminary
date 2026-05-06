#!/usr/bin/env bash
# Smoke test for S220: Evals tab UI.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

test -f "$ROOT/frontend/src/pages/Evals.tsx"
test -f "$ROOT/frontend/src/components/evals/DatasetCard.tsx"
test -f "$ROOT/frontend/src/components/evals/GenerateDatasetDialog.tsx"
test -f "$ROOT/frontend/src/components/evals/DatasetDetail.tsx"
test -f "$ROOT/frontend/src/components/evals/QuestionList.tsx"
test -f "$ROOT/frontend/src/components/evals/RunEvalDialog.tsx"
test -f "$ROOT/frontend/src/components/evals/ScoresTable.tsx"

grep -q 'path="/evals"' "$ROOT/frontend/src/App.tsx"
grep -q 'label: "Evals"' "$ROOT/frontend/src/App.tsx"
grep -q '/evals/datasets' "$ROOT/frontend/src/pages/Evals.tsx"

(cd "$ROOT/frontend" && npx tsc --noEmit -p tsconfig.app.json)

echo "PASS: S220 -- Evals tab route, workflow components, and frontend typecheck are green"
