#!/usr/bin/env bash
# Smoke test for S207: naming normalization check + apply endpoints
set -euo pipefail

# BSD mktemp only substitutes Xs at the END of a template, so
# `mktemp /tmp/foo.XXXXXX.json` created that name literally: the script worked
# once per machine and then failed "File exists" forever. One per-run directory
# keeps the extensions -- uploads are validated on them -- and cleans up itself.
SMOKE_TMPDIR=$(mktemp -d)
trap 'rm -rf "$SMOKE_TMPDIR"' EXIT

BASE="${LUMINARY_URL:-http://localhost:7820}"
PASS=0
FAIL=0

check() {
  local desc="$1" expect="$2" actual="$3"
  if [ "$actual" = "$expect" ]; then
    echo "  PASS: $desc (HTTP $actual)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc (expected $expect, got $actual)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== S207 Smoke Test ==="

# 1. POST /notes/cluster/normalize-check returns 200
TMPFILE="$SMOKE_TMPDIR/s207.json"
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X POST "$BASE/notes/cluster/normalize-check")
check "POST /notes/cluster/normalize-check" "200" "$STATUS"

# Response should be a JSON array
BODY=$(cat "$TMPFILE")
echo "  normalize-check response: ${BODY:0:200}"
rm -f "$TMPFILE"

# 2. POST /notes/cluster/normalize-apply with empty list returns 200
TMPFILE2="$SMOKE_TMPDIR/s207_apply.json"
STATUS2=$(curl -s -o "$TMPFILE2" -w "%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -d '{"fixes":[]}' \
  "$BASE/notes/cluster/normalize-apply")
check "POST /notes/cluster/normalize-apply (empty)" "200" "$STATUS2"

BODY2=$(cat "$TMPFILE2")
echo "  normalize-apply response: ${BODY2:0:200}"
rm -f "$TMPFILE2"

# 3. TypeScript compiles
echo "  Checking tsc..."
cd "$(dirname "$0")/../../frontend"
npx tsc --noEmit > /dev/null 2>&1 && {
  echo "  PASS: tsc --noEmit"
  PASS=$((PASS + 1))
} || {
  echo "  FAIL: tsc --noEmit"
  FAIL=$((FAIL + 1))
}

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
