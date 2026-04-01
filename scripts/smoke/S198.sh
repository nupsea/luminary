#!/usr/bin/env bash
# S198 Smoke Test — Highlight reliability: text viewer, PDF edge cases, large selection
# Verifies:
#   1. POST /annotations with page_number field accepted (201)
#   2. GET /annotations?document_id=... returns annotation with page_number
#   3. Frontend unit tests pass (resolveSourceRefUtils)
#   4. TypeScript compilation passes

set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"
FAIL=0
TMPFILE=$(mktemp /tmp/smoke_s198_XXXXXX.json)

echo "=== S198 Smoke: highlight reliability ==="

DOC_ID="smoke-doc-s198-$(date +%s)"
SECTION_ID="smoke-sec-1"

# 1. POST /annotations with page_number
echo "[1/4] POST /annotations with page_number (expect 201)"
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X POST "${BASE}/annotations" \
  -H "Content-Type: application/json" \
  -d "{\"document_id\":\"${DOC_ID}\",\"section_id\":\"${SECTION_ID}\",\"selected_text\":\"test highlight\",\"start_offset\":0,\"end_offset\":14,\"color\":\"yellow\",\"page_number\":3}")
if [ "$STATUS" = "201" ]; then
  echo "  PASS: annotation created with page_number"
  # Verify page_number is in response
  if python3 -c "import json,sys; d=json.load(open('$TMPFILE')); assert d.get('page_number')==3, f'got {d.get(\"page_number\")}'" 2>/dev/null; then
    echo "  PASS: page_number=3 in response"
  else
    echo "  FAIL: page_number not 3 in response"
    FAIL=1
  fi
else
  echo "  FAIL: expected 201 got $STATUS"
  FAIL=1
fi

# 2. GET /annotations for the document
echo "[2/4] GET /annotations?document_id=${DOC_ID} (expect 200)"
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "${BASE}/annotations?document_id=${DOC_ID}")
if [ "$STATUS" = "200" ]; then
  COUNT=$(python3 -c "import json; print(len(json.load(open('$TMPFILE'))))" 2>/dev/null || echo "0")
  if [ "$COUNT" -ge 1 ]; then
    echo "  PASS: $COUNT annotation(s) returned"
  else
    echo "  FAIL: expected >= 1 annotation, got $COUNT"
    FAIL=1
  fi
else
  echo "  FAIL: expected 200 got $STATUS"
  FAIL=1
fi

# 3. Frontend unit tests
echo "[3/4] vitest resolveSourceRefUtils"
cd "$REPO/frontend"
if npx vitest run src/components/reader/resolveSourceRefUtils.test.ts 2>&1 | tail -3; then
  echo "  PASS: vitest"
else
  echo "  FAIL: vitest"
  FAIL=1
fi

# 4. TypeScript compilation
echo "[4/4] npx tsc --noEmit"
if npx tsc --noEmit 2>&1; then
  echo "  PASS: tsc"
else
  echo "  FAIL: tsc"
  FAIL=1
fi

rm -f "$TMPFILE"

if [ "$FAIL" -ne 0 ]; then
  echo "=== S198 SMOKE FAILED ==="
  exit 1
fi

echo "=== S198 SMOKE PASSED ==="
exit 0
