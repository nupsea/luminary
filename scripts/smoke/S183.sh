#!/usr/bin/env bash
# Smoke test for S183 -- Learning tab stats bar: verify endpoints used by LibraryStatsBar
set -euo pipefail

BASE="http://localhost:8000"
PASS=0
FAIL=0

check() {
  local desc="$1"
  local status="$2"
  local expected="$3"
  local body="$4"
  local field="$5"

  if [ "$status" -eq "$expected" ]; then
    echo "[PASS] $desc (HTTP $status)"
    PASS=$((PASS + 1))
  else
    echo "[FAIL] $desc (expected HTTP $expected, got $status)"
    FAIL=$((FAIL + 1))
  fi

  if [ -n "$field" ]; then
    if echo "$body" | python3 -c "import sys, json; d=json.load(sys.stdin); assert $field, 'field check failed'" 2>/dev/null; then
      echo "[PASS] $desc field check: $field"
      PASS=$((PASS + 1))
    else
      echo "[FAIL] $desc field check: $field"
      echo "       Body: $(echo "$body" | head -c 300)"
      FAIL=$((FAIL + 1))
    fi
  fi
}

TMPFILE=$(mktemp)

# Test 1: GET /documents returns 200 with total field (used for books count pill)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/documents")
BODY=$(cat "$TMPFILE")
check "GET /documents returns 200" "$STATUS" "200" "$BODY" ""
check "GET /documents has total field" "$STATUS" "200" "$BODY" "'total' in d"
check "GET /documents total is int" "$STATUS" "200" "$BODY" "isinstance(d['total'], int)"

# Test 2: GET /notes returns 200 list (used for notes count pill)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/notes")
BODY=$(cat "$TMPFILE")
check "GET /notes returns 200" "$STATUS" "200" "$BODY" ""
check "GET /notes returns array" "$STATUS" "200" "$BODY" "isinstance(d, list)"

# Test 3: GET /study/due-count returns 200 with due_today field (used for cards due pill)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/study/due-count")
BODY=$(cat "$TMPFILE")
check "GET /study/due-count returns 200" "$STATUS" "200" "$BODY" ""
check "GET /study/due-count has due_today field" "$STATUS" "200" "$BODY" "'due_today' in d"
check "GET /study/due-count due_today is int" "$STATUS" "200" "$BODY" "isinstance(d['due_today'], int)"

# Test 4: GET /study/sessions returns 200 with items field (used for avg mastery pill)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/study/sessions?page_size=20")
BODY=$(cat "$TMPFILE")
check "GET /study/sessions returns 200" "$STATUS" "200" "$BODY" ""
check "GET /study/sessions has items field" "$STATUS" "200" "$BODY" "'items' in d"
check "GET /study/sessions items is list" "$STATUS" "200" "$BODY" "isinstance(d['items'], list)"

rm -f "$TMPFILE"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
