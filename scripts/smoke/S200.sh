#!/usr/bin/env bash
# S200 Smoke Test -- PDF Viewer: internal links, external links, rendering fidelity
# Verifies:
#   1. Backend /documents endpoint is reachable (viewer's dependency)
#   2. Frontend pdfLinkService unit tests pass
#   3. TypeScript compilation passes

set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"
FAIL=0

echo "=== S200 Smoke: PDF Viewer links and rendering ==="

# 1. GET /documents returns 200 (backend reachable, PDF file endpoint operational)
echo "[1/3] GET /documents (expect 200)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/documents")
if [ "$STATUS" = "200" ]; then
  echo "  PASS: backend reachable"
else
  echo "  FAIL: expected 200 got $STATUS"
  FAIL=1
fi

# 2. Frontend unit tests for pdfLinkService
echo "[2/3] vitest pdfLinkService"
cd "$REPO/frontend"
if npx vitest run src/components/reader/pdfLinkService.test.ts 2>&1 | tail -3; then
  echo "  PASS: vitest"
else
  echo "  FAIL: vitest"
  FAIL=1
fi

# 3. TypeScript compilation
echo "[3/3] npx tsc --noEmit"
if npx tsc --noEmit 2>&1; then
  echo "  PASS: tsc"
else
  echo "  FAIL: tsc"
  FAIL=1
fi

if [ "$FAIL" -ne 0 ]; then
  echo "=== S200 SMOKE FAILED ==="
  exit 1
fi

echo "=== S200 SMOKE PASSED ==="
exit 0
