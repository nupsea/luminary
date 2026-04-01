#!/usr/bin/env bash
# S197 Smoke Test — Compare notes with book: auto-collection gap analysis
# Verifies:
#   1. GET /collections/by-document/{doc_id} returns 404 for non-existent doc
#   2. POST /collections/auto/{doc_id} creates an auto-collection
#   3. GET /collections/by-document/{doc_id} returns the auto-collection
#   4. TypeScript compilation passes

set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"
FAIL=0
TMPFILE=$(mktemp /tmp/smoke_s197_XXXXXX.json)

echo "=== S197 Smoke: auto-collection gap analysis ==="

# Use a fake doc ID for isolation
DOC_ID="smoke-doc-s197-$(date +%s)"

# 1. GET /collections/by-document/{doc_id} should 404 for unknown doc
echo "[1/4] GET /collections/by-document/${DOC_ID} (expect 404)"
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "${BASE}/collections/by-document/${DOC_ID}")
if [ "$STATUS" = "404" ]; then
  echo "  PASS: 404 for unknown doc"
else
  echo "  FAIL: expected 404 got $STATUS"
  FAIL=1
fi

# 2. POST /collections/auto/{doc_id} creates auto-collection
echo "[2/4] POST /collections/auto/${DOC_ID} (expect 201)"
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X POST "${BASE}/collections/auto/${DOC_ID}")
if [ "$STATUS" = "201" ]; then
  echo "  PASS: auto-collection created"
else
  echo "  FAIL: expected 201 got $STATUS"
  FAIL=1
fi

# 3. GET /collections/by-document/{doc_id} now returns the collection
echo "[3/4] GET /collections/by-document/${DOC_ID} (expect 200)"
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "${BASE}/collections/by-document/${DOC_ID}")
if [ "$STATUS" = "200" ]; then
  echo "  PASS: auto-collection found"
else
  echo "  FAIL: expected 200 got $STATUS"
  FAIL=1
fi

# 4. TypeScript compilation
echo "[4/4] npx tsc --noEmit"
cd "$REPO/frontend"
if npx tsc --noEmit 2>&1; then
  echo "  PASS: tsc"
else
  echo "  FAIL: tsc"
  FAIL=1
fi

rm -f "$TMPFILE"

if [ "$FAIL" -ne 0 ]; then
  echo "=== S197 SMOKE FAILED ==="
  exit 1
fi

echo "=== S197 SMOKE PASSED ==="
exit 0
