#!/usr/bin/env bash
# Smoke test for S184: Flashcard search and unified browse.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"
PASS=0
FAIL=0

check() {
  local desc="$1" url="$2" expected="$3"
  TMPFILE=$(mktemp /tmp/s184_XXXXXX)
  HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$url")
  if [ "$HTTP" != "$expected" ]; then
    echo "FAIL: $desc — expected $expected, got $HTTP"
    cat "$TMPFILE"
    rm -f "$TMPFILE"
    FAIL=$((FAIL + 1))
    return
  fi
  rm -f "$TMPFILE"
  PASS=$((PASS + 1))
  echo "PASS: $desc"
}

# 1. Health check
check "Health check" "${BASE}/health" "200"

# 2. GET /flashcards/search with no params returns 200 + JSON with items array
TMPFILE=$(mktemp /tmp/s184_XXXXXX)
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" "${BASE}/flashcards/search")
if [ "$HTTP" != "200" ]; then
  echo "FAIL: search no params — expected 200, got $HTTP"
  FAIL=$((FAIL + 1))
else
  # Verify response shape has items and total
  if python3 -c "import json,sys; d=json.load(open('$TMPFILE')); assert 'items' in d and 'total' in d" 2>/dev/null; then
    echo "PASS: search no params — 200 with items+total"
    PASS=$((PASS + 1))
  else
    echo "FAIL: search no params — response missing items or total"
    FAIL=$((FAIL + 1))
  fi
fi
rm -f "$TMPFILE"

# 3. GET /flashcards/search?query=test returns 200
check "search with query param" "${BASE}/flashcards/search?query=test" "200"

# 4. GET /flashcards/search?bloom_level_min=3 returns 200
check "search with bloom_level_min" "${BASE}/flashcards/search?bloom_level_min=3" "200"

# 5. GET /flashcards/search?fsrs_state=new returns 200
check "search with fsrs_state" "${BASE}/flashcards/search?fsrs_state=new" "200"

# 6. GET /flashcards/search?flashcard_type=concept returns 200
check "search with flashcard_type" "${BASE}/flashcards/search?flashcard_type=concept" "200"

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
echo "S184 smoke: ALL PASSED"
