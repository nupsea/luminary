#!/usr/bin/env bash
# Smoke test for S186: Chat inline document scope selector
# Verifies the backend endpoints that the new combobox depends on.
set -euo pipefail

BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"
PASS=0
FAIL=0

check() {
  local desc="$1" url="$2" expected_status="$3" body_check="${4:-}"
  TMPFILE=$(mktemp /tmp/s186_XXXXXX)
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

# AC2: Combobox fetches documents sorted by most recently viewed (opened_at desc)
check "GET /documents?sort=last_accessed returns 200 with items array" \
  "$BASE/documents?sort=last_accessed&page=1&page_size=100" \
  200 \
  "assert isinstance(d.get('items'), list)"

# AC5: ChatSettingsDrawer still works (model + web search settings)
check "GET /settings/llm returns 200" \
  "$BASE/settings/llm" \
  200

check "GET /settings/web-search returns 200" \
  "$BASE/settings/web-search" \
  200

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
