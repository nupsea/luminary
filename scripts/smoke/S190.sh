#!/usr/bin/env bash
# Smoke test for S190 -- Tag search: type-ahead search in Notes sidebar
# Frontend-only story, but verifies GET /tags/tree still returns 200 + array
set -euo pipefail

# BSD mktemp only substitutes Xs at the END of a template, so
# `mktemp /tmp/foo.XXXXXX.json` created that name literally: the script worked
# once per machine and then failed "File exists" forever. One per-run directory
# keeps the extensions -- uploads are validated on them -- and cleans up itself.
SMOKE_TMPDIR=$(mktemp -d)
trap 'rm -rf "$SMOKE_TMPDIR"' EXIT

BASE="http://localhost:7820"

echo "--- S190 smoke: GET /tags/tree ---"
TMPFILE="$SMOKE_TMPDIR/s190.json"
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/tags/tree")
BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"

if [ "$STATUS" != "200" ]; then
  echo "FAIL: GET /tags/tree returned $STATUS (expected 200)"
  exit 1
fi

# Body must be a JSON array
if ! echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert isinstance(d, list), 'not a list'"; then
  echo "FAIL: response is not a JSON array"
  exit 1
fi

echo "PASS: GET /tags/tree returns 200 with array response"
echo "--- S190 smoke: PASS ---"
