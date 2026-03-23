#!/usr/bin/env bash
# Smoke test for S51: Study tab — GET /study/due and POST /flashcards/generate error shape.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# 1. GET /study/due — must return 200 with JSON array
BODY=$(curl -sf "${BASE}/study/due?limit=1")
if [ -z "$BODY" ]; then
  echo "FAIL: GET /study/due returned empty body"
  exit 1
fi
# Must be a JSON array (starts with [)
if ! echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert isinstance(d, list)" 2>/dev/null; then
  echo "FAIL: GET /study/due did not return a JSON array"
  exit 1
fi

# 2. POST /flashcards/generate with missing document → 422 (validation error), not 500
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/flashcards/generate" \
  -H "Content-Type: application/json" \
  -d '{"scope":"full","count":1}')
if [ "$HTTP_CODE" != "422" ]; then
  echo "FAIL: POST /flashcards/generate with missing document_id returned ${HTTP_CODE} (expected 422)"
  exit 1
fi

echo "PASS: /study/due returns 200 array; /flashcards/generate validates inputs (422)"
