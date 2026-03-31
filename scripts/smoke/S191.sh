#!/usr/bin/env bash
# S191 Smoke Test — Library document action menu
# Frontend-only story: no new backend endpoints.
# Verifies TypeScript compilation and Vitest unit tests pass.

set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
FAIL=0

echo "=== S191 Smoke: Frontend-only story ==="

# Gate 1: TypeScript compilation
echo "[1/2] npx tsc --noEmit"
cd "$REPO/frontend"
if npx tsc --noEmit 2>&1; then
  echo "  PASS: tsc"
else
  echo "  FAIL: tsc"
  FAIL=1
fi

# Gate 2: Vitest for docActionUtils
echo "[2/2] vitest run docActionUtils.test.ts"
if npx vitest run src/lib/docActionUtils.test.ts 2>&1; then
  echo "  PASS: vitest"
else
  echo "  FAIL: vitest"
  FAIL=1
fi

if [ "$FAIL" -ne 0 ]; then
  echo "=== S191 SMOKE FAILED ==="
  exit 1
fi

echo "=== S191 SMOKE PASSED ==="
exit 0
