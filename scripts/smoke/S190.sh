#!/usr/bin/env bash
# Smoke test for S190 -- Tag search: type-ahead search in Notes sidebar
# Frontend-only story, but verifies GET /tags/tree still returns 200 + array
set -euo pipefail

BASE="http://localhost:7820"

echo "--- S190 smoke: GET /tags/tree ---"
TMPFILE=$(mktemp /tmp/s190_XXXXXX.json)
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
