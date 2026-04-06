#!/usr/bin/env bash
# Smoke test for S188: Flashcard generation context-rich questions with source grounding
set -euo pipefail

BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"
PASS=0
FAIL=0

check() {
  local desc="$1" url="$2" expected_status="$3" body_check="${4:-}"
  TMPFILE=$(mktemp /tmp/s188_XXXXXX)
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

check_post() {
  local desc="$1" url="$2" data="$3" expected_status="$4" body_check="${5:-}"
  TMPFILE=$(mktemp /tmp/s188_XXXXXX)
  HTTP_CODE=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "$data" "$url")
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

# AC: GET /flashcards/{document_id} returns list with section_heading field in schema
# Use a non-existent doc to get empty list (still validates endpoint works)
check "GET /flashcards for non-existent doc returns 200 with list" \
  "$BASE/flashcards/smoke-s188-doc" \
  200 \
  "assert isinstance(d, list)"

# AC: GET /flashcards/search returns 200 with items array
check "GET /flashcards/search returns 200" \
  "$BASE/flashcards/search?q=test" \
  200 \
  "assert 'items' in d"

# AC: GET /flashcards/decks returns 200 with list
check "GET /flashcards/decks returns 200 with list" \
  "$BASE/flashcards/decks" \
  200 \
  "assert isinstance(d, list)"

# AC: Verify FlashcardResponse schema includes section_heading via OpenAPI
TMPFILE=$(mktemp /tmp/s188_XXXXXX)
HTTP_CODE=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/openapi.json")
BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"

if [ "$HTTP_CODE" = "200" ]; then
  if echo "$BODY" | python3 -c "
import sys, json
spec = json.load(sys.stdin)
schemas = spec.get('components', {}).get('schemas', {})
fr = schemas.get('FlashcardResponse', {}).get('properties', {})
assert 'section_heading' in fr, 'section_heading not in FlashcardResponse'
assert 'bloom_level' in fr, 'bloom_level not in FlashcardResponse'
" 2>/dev/null; then
    echo "PASS: OpenAPI schema includes section_heading and bloom_level in FlashcardResponse"
    PASS=$((PASS + 1))
  else
    echo "FAIL: OpenAPI schema missing section_heading or bloom_level in FlashcardResponse"
    FAIL=$((FAIL + 1))
  fi
else
  echo "FAIL: Could not fetch openapi.json (HTTP $HTTP_CODE)"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
