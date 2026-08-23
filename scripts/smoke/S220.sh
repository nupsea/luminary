#!/usr/bin/env bash
# Smoke test for S220: Evals tab UI.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# The tab was renamed: pages/Evals.tsx is now pages/Quality.tsx, DatasetCard and
# RunEvalDialog/ScoresTable were replaced by ResultsDashboard and RunConsole, and
# /evals survives only as a redirect. This checked the old names and so reported
# a missing feature that had merely moved.
test -f "$ROOT/frontend/src/pages/Quality.tsx"
for component in DatasetDetail GenerateDatasetDialog QuestionList ResultsDashboard RunConsole; do
  test -f "$ROOT/frontend/src/components/evals/${component}.tsx" \
    || { echo "FAIL: components/evals/${component}.tsx missing"; exit 1; }
done

grep -q 'path="/evals"' "$ROOT/frontend/src/App.tsx"   # kept as a redirect
grep -q '/evals/datasets' "$ROOT/frontend/src/pages/Quality.tsx"

# Not `npx tsc --noEmit`: tsconfig is solution-style, so that resolves zero files
# and exits 0 with real errors present. The project binary with -b walks the refs.
(cd "$ROOT/frontend" && ./node_modules/.bin/tsc -b --noEmit --force)

echo "PASS: S220 -- Quality tab route, workflow components, and frontend typecheck are green"
