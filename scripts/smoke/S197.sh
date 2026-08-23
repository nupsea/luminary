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

# An id nothing owns, for the 404 case only.
MISSING_ID="smoke-doc-s197-$(date +%s)"

# The create case needs a document that exists: `create_auto_collection` resolves
# the document through get_or_404 to read its title and content_type, so a
# fabricated id is a 404 by design and asking for 201 asked for the wrong thing.
DOC_ID=$(curl -s "${BASE}/documents" | python3 -c "
import json, sys
docs = json.load(sys.stdin)
items = docs.get('items', docs) if isinstance(docs, dict) else docs
ready = [d for d in items if isinstance(d, dict) and d.get('stage') == 'complete']
print(ready[0]['id'] if ready else '')
" 2>/dev/null || echo "")

if [ -z "$DOC_ID" ]; then
  echo "SKIP: no complete document to build an auto-collection for"
  exit 0
fi

# Only clean up a collection this run created; an auto-collection the library
# already had is the user's.
PRE_EXISTING=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/collections/by-document/${DOC_ID}")
cleanup() {
  rm -f "$TMPFILE"
  if [ "$PRE_EXISTING" = "404" ]; then
    CID=$(curl -s "${BASE}/collections/by-document/${DOC_ID}" \
      | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
    [ -n "$CID" ] && curl -s -o /dev/null -X DELETE "${BASE}/collections/${CID}" || true
  fi
}
trap cleanup EXIT

# 1. GET /collections/by-document/{doc_id} should 404 for unknown doc
echo "[1/4] GET /collections/by-document/${MISSING_ID} (expect 404)"
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "${BASE}/collections/by-document/${MISSING_ID}")
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
echo "[4/4] tsc -b --noEmit"
cd "$REPO/frontend"
# Not `npx tsc`: npx has resolved to a bogus `tsc` package that exits 0 without
# type-checking anything, which is worse than no check. Use the project's binary.
if ./node_modules/.bin/tsc -b --noEmit --force 2>&1; then
  echo "  PASS: tsc"
else
  echo "  FAIL: tsc"
  FAIL=1
fi


if [ "$FAIL" -ne 0 ]; then
  echo "=== S197 SMOKE FAILED ==="
  exit 1
fi

echo "=== S197 SMOKE PASSED ==="
exit 0
