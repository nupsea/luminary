#!/usr/bin/env bash
# S196 Smoke Test — Chat: non-destructive scope clear
# Frontend-only story: no new backend endpoints.
# Verifies TypeScript compilation passes (no regressions in Chat.tsx).

set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
FAIL=0

echo "=== S196 Smoke: Frontend-only story ==="

# Gate 1: TypeScript compilation
echo "[1/1] npx tsc --noEmit"
cd "$REPO/frontend"
if npx tsc --noEmit 2>&1; then
  echo "  PASS: tsc"
else
  echo "  FAIL: tsc"
  FAIL=1
fi

if [ "$FAIL" -ne 0 ]; then
  echo "=== S196 SMOKE FAILED ==="
  exit 1
fi

echo "=== S196 SMOKE PASSED ==="
exit 0
