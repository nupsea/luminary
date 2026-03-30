#!/usr/bin/env bash
# Smoke test for S189: Auto-organize guided plan with confirmation workflow
set -euo pipefail

BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"
PASS=0
FAIL=0

check() {
  local desc="$1" url="$2" expected_status="$3" body_check="${4:-}"
  TMPFILE=$(mktemp /tmp/s189_XXXXXX)
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
  local desc="$1" url="$2" expected_status="$3" data="$4" body_check="${5:-}"
  TMPFILE=$(mktemp /tmp/s189_XXXXXX)
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

# -- POST /notes/cluster triggers clustering (returns 202 with queued or cached)
check_post "POST /notes/cluster" "$BASE/notes/cluster" 202 '{}' "assert 'queued' in d or 'cached' in d"

# -- GET /notes/cluster/suggestions returns list (may be empty)
check "GET /notes/cluster/suggestions" "$BASE/notes/cluster/suggestions" 200 "assert isinstance(d, list)"

# -- POST /notes/cluster/suggestions/batch-accept with empty list returns 200
check_post "POST batch-accept empty list" "$BASE/notes/cluster/suggestions/batch-accept" 200 '{"items":[]}' "assert 'collection_ids' in d"

# -- POST /notes/cluster/suggestions/batch-accept with nonexistent ID returns 200 (no error, 0 created)
check_post "POST batch-accept nonexistent" "$BASE/notes/cluster/suggestions/batch-accept" 200 '{"items":[{"suggestion_id":"nonexistent-id-999","name_override":null}]}' "assert d['collection_ids'] == []"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
