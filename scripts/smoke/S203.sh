#!/usr/bin/env bash
# Smoke test for S203: PDF Viewer in-page and cross-page text search
# Frontend-only story -- verifies new files exist, Vitest passes, and tsc compiles.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=true

echo "=== S203 Smoke Test ==="

# 1. Verify new source files exist
echo "--- Check 1: New source files ---"
for f in \
  "frontend/src/components/reader/PdfSearchBar.tsx" \
  "frontend/src/components/reader/pdfSearchUtils.ts" \
  "frontend/src/components/reader/pdfSearchUtils.test.ts"; do
  if [ -f "$REPO_ROOT/$f" ]; then
    echo "  OK: $f"
  else
    echo "  FAIL: $f missing"
    PASS=false
  fi
done

# 2. Vitest unit tests for search utils
echo "--- Check 2: Vitest pdfSearchUtils ---"
if (cd "$REPO_ROOT/frontend" && npx vitest run src/components/reader/pdfSearchUtils.test.ts 2>&1 | tail -5); then
  echo "PASS: pdfSearchUtils tests pass"
else
  echo "FAIL: pdfSearchUtils tests failed"
  PASS=false
fi

# 3. TypeScript compilation
echo "--- Check 3: tsc --noEmit ---"
if (cd "$REPO_ROOT/frontend" && npx tsc --noEmit 2>&1); then
  echo "PASS: tsc --noEmit exits 0"
else
  echo "FAIL: tsc --noEmit had errors"
  PASS=false
fi

if [ "$PASS" = true ]; then
  echo "=== S203 Smoke: ALL PASSED ==="
  exit 0
else
  echo "=== S203 Smoke: SOME FAILED ==="
  exit 1
fi
