#!/usr/bin/env bash
# Smoke test for S87 -- Notes focused editor dialog
# Verifies TypeScript compiles and the frontend builds without errors.
# Runtime dialog behaviour requires a browser and cannot be verified headlessly.
set -euo pipefail

FRONTEND_DIR="$(cd "$(dirname "$0")/../../frontend" && pwd)"

echo "S87 smoke: npx tsc --noEmit"
cd "$FRONTEND_DIR"
npx tsc --noEmit
echo "PASS: tsc --noEmit exits 0"

echo "S87 smoke: npm run build"
npm run build
echo "PASS: npm run build exits 0"

echo "S87 smoke: all checks passed"
