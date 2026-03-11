#!/usr/bin/env bash
# Smoke test for S93: Flashcard generation from notes.
# Requires the backend to be running on localhost:8000.

set -euo pipefail

BASE="http://localhost:8000"
NOTE_ID=""

cleanup() {
  if [ -n "$NOTE_ID" ]; then
    curl -s -o /dev/null -X DELETE "${BASE}/notes/${NOTE_ID}" || true
  fi
}
trap cleanup EXIT

# 1. Create a tagged note
CREATE_RESP=$(curl -s -X POST "${BASE}/notes" \
  -H "Content-Type: application/json" \
  -d '{"content":"The Cheshire Cat can vanish leaving only its grin","tags":["s93smoke"]}')
NOTE_ID=$(echo "$CREATE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

if [ -z "$NOTE_ID" ]; then
  echo "FAIL: POST /notes did not return an id"
  exit 1
fi

# 2. POST /notes/flashcards/generate with no tag or ids — expect 422
HTTP_422=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/notes/flashcards/generate" \
  -H "Content-Type: application/json" \
  -d '{"count":2}')

if [ "$HTTP_422" != "422" ]; then
  echo "FAIL: POST /notes/flashcards/generate without scope returned ${HTTP_422} (expected 422)"
  exit 1
fi

echo "PASS: S93 -- note created, /notes/flashcards/generate 422 without scope"
