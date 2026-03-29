#!/usr/bin/env bash
# Smoke test for S187: Chat document-aware contextual recommendations
set -euo pipefail

BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"
PASS=0
FAIL=0

check() {
  local desc="$1" url="$2" expected_status="$3" body_check="${4:-}"
  TMPFILE=$(mktemp /tmp/s187_XXXXXX)
  HTTP_CODE=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$url")
  BODY=$(cat "$TMPFILE")
  rm -f "$TMPFILE"

  if [ "$HTTP_CODE" != "$expected_status" ]; then
    echo "FAIL: $desc -- expected $expected_status, got $HTTP_CODE"
    FAIL=$((FAIL + 1))
    return
  fi

  if [ -n "$body_check" ]; then
    if ! echo "$BODY" | python3 -c "import sys, json; d=json.load(sys.stdin); $body_check" 2>/dev/null; then
      echo "FAIL: $desc -- body check failed: $body_check"
      echo "  Body: $(echo "$BODY" | head -c 200)"
      FAIL=$((FAIL + 1))
      return
    fi
  fi

  echo "PASS: $desc"
  PASS=$((PASS + 1))
}

# AC1: GET /chat/suggestions with no document_id returns 4 suggestions
check "GET /chat/suggestions (all scope) returns 200 with suggestions array" \
  "$BASE/chat/suggestions" \
  200 \
  "assert isinstance(d.get('suggestions'), list) and len(d['suggestions']) == 4"

# AC2: GET /chat/suggestions with a document_id returns 200 (may be fake doc -> onboarding)
check "GET /chat/suggestions with document_id returns 200" \
  "$BASE/chat/suggestions?document_id=smoke-doc-s187" \
  200 \
  "assert isinstance(d.get('suggestions'), list) and len(d['suggestions']) == 4"

# AC7: GET /chat/confusion-signals should return 404 (endpoint removed)
TMPFILE=$(mktemp /tmp/s187_XXXXXX)
HTTP_CODE=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/chat/confusion-signals")
rm -f "$TMPFILE"
if [ "$HTTP_CODE" = "404" ] || [ "$HTTP_CODE" = "405" ]; then
  echo "PASS: GET /chat/confusion-signals returns $HTTP_CODE (endpoint removed)"
  PASS=$((PASS + 1))
else
  echo "FAIL: GET /chat/confusion-signals expected 404/405, got $HTTP_CODE"
  FAIL=$((FAIL + 1))
fi

# AC: GET /chat/explorations still works (not removed)
check "GET /chat/explorations still returns 200" \
  "$BASE/chat/explorations?document_id=smoke-doc-s187" \
  200 \
  "assert isinstance(d, list)"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
