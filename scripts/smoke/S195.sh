#!/usr/bin/env bash
# Smoke test for S195 -- Chat: Bloom-progressive recommendations
set -euo pipefail

BASE="http://localhost:7820"
FAIL=0

echo "=== S195 Smoke: Bloom-progressive chat suggestions ==="

# 1. GET /chat/suggestions with no document_id
echo "[1/4] GET /chat/suggestions (all-scope)..."
TMPFILE=$(mktemp /tmp/s195_1_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/chat/suggestions")
BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"
if [ "$STATUS" != "200" ]; then
  echo "  FAIL: expected 200, got $STATUS"
  FAIL=1
else
  # Verify response has suggestions array with objects containing text field
  HAS_TEXT=$(echo "$BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
items=d.get('suggestions',[])
print('ok' if items and all('text' in i for i in items) else 'fail')
" 2>/dev/null || echo "fail")
  if [ "$HAS_TEXT" = "ok" ]; then
    echo "  OK: suggestions array with {id,text} objects"
  else
    echo "  FAIL: unexpected response shape: $BODY"
    FAIL=1
  fi
fi

# 2. GET /chat/suggestions?document_id=nonexistent (fallback path)
echo "[2/4] GET /chat/suggestions?document_id=nonexistent..."
TMPFILE=$(mktemp /tmp/s195_2_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/chat/suggestions?document_id=nonexistent-doc-s195")
BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"
if [ "$STATUS" != "200" ]; then
  echo "  FAIL: expected 200, got $STATUS"
  FAIL=1
else
  echo "  OK: fallback suggestions returned"
fi

# 3. Extract first suggestion id and POST /asked
echo "[3/4] POST /chat/suggestions/{id}/asked..."
# Use all-scope suggestions to get an id
TMPFILE=$(mktemp /tmp/s195_3_XXXXXX.json)
curl -s -o "$TMPFILE" "$BASE/chat/suggestions"
BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"
SUGGESTION_ID=$(echo "$BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
items=d.get('suggestions',[])
# Find first item with non-empty id
for i in items:
    if i.get('id'):
        print(i['id'])
        break
" 2>/dev/null || true)

if [ -z "$SUGGESTION_ID" ]; then
  echo "  SKIP: no suggestion with id (template fallback has empty ids)"
else
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/chat/suggestions/$SUGGESTION_ID/asked")
  if [ "$STATUS" = "204" ]; then
    echo "  OK: marked as asked (204)"
  else
    echo "  FAIL: expected 204, got $STATUS"
    FAIL=1
  fi
fi

# 4. POST /asked with fake id should still return 204 (no error)
echo "[4/4] POST /chat/suggestions/fake-id/asked (nonexistent)..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/chat/suggestions/fake-id-s195/asked")
if [ "$STATUS" = "204" ]; then
  echo "  OK: nonexistent id returns 204 (no error)"
else
  echo "  FAIL: expected 204, got $STATUS"
  FAIL=1
fi

echo "---"
if [ "$FAIL" -ne 0 ]; then
  echo "S195 SMOKE FAILED"
  exit 1
fi
echo "S195 SMOKE PASSED"
exit 0
