#!/usr/bin/env bash
# Smoke test for S180 -- Chat interface simplification
# Verifies Chat-adjacent backend endpoints still respond (no backend changes in this story)
set -euo pipefail

BASE="${LUMINARY_API_BASE:-http://localhost:7820}"
PASS=0
FAIL=0

check() {
  local label="$1"
  local expected="$2"
  local actual="$3"
  if [ "$actual" = "$expected" ]; then
    echo "PASS: $label (HTTP $actual)"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label -- expected HTTP $expected, got $actual"
    FAIL=$((FAIL + 1))
  fi
}

# GET /settings/llm -- LLM configuration endpoint
TMPFILE=$(mktemp)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/settings/llm")
check "GET /settings/llm" "200" "$STATUS"
BODY=$(cat "$TMPFILE")
if echo "$BODY" | grep -q "processing_mode"; then
  echo "PASS: /settings/llm body contains processing_mode"
  PASS=$((PASS + 1))
else
  echo "FAIL: /settings/llm body missing processing_mode -- got: $BODY"
  FAIL=$((FAIL + 1))
fi
rm -f "$TMPFILE"

# GET /settings/web-search -- web search configuration endpoint
TMPFILE=$(mktemp)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/settings/web-search")
check "GET /settings/web-search" "200" "$STATUS"
BODY=$(cat "$TMPFILE")
if echo "$BODY" | grep -q "enabled"; then
  echo "PASS: /settings/web-search body contains enabled"
  PASS=$((PASS + 1))
else
  echo "FAIL: /settings/web-search body missing enabled -- got: $BODY"
  FAIL=$((FAIL + 1))
fi
rm -f "$TMPFILE"

# GET /chat/confusion-signals -- confusion signal endpoint
TMPFILE=$(mktemp)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/chat/confusion-signals")
check "GET /chat/confusion-signals" "200" "$STATUS"
rm -f "$TMPFILE"

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
