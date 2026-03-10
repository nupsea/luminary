#!/usr/bin/env bash
# Smoke test for S92: Notes as chat context -- POST /chat/stream with notes intent.
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

# 1. Create a note to search against
CREATE_RESP=$(curl -s -X POST "${BASE}/notes" \
  -H "Content-Type: application/json" \
  -d '{"content":"The Cheshire Cat can vanish leaving only its grin","tags":[]}')
NOTE_ID=$(echo "$CREATE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

if [ -z "$NOTE_ID" ]; then
  echo "FAIL: POST /notes did not return an id"
  exit 1
fi

# 2. POST /chat/stream with a notes-intent query; assert HTTP 200
HTTP_CODE=$(curl -s -o /tmp/s92_chat.txt -w "%{http_code}" -X POST "${BASE}/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{"query":"what did I note about my reading","document_ids":[],"scope":"all"}')

if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: POST /chat/stream returned ${HTTP_CODE} (expected 200)"
  exit 1
fi

# 3. Assert SSE response contains data lines
if ! grep -q "^data:" /tmp/s92_chat.txt; then
  echo "FAIL: SSE response contains no data: lines"
  cat /tmp/s92_chat.txt
  exit 1
fi

echo "PASS: S92 -- note created, chat/stream returns HTTP 200 with SSE data lines for notes-intent query"
