#!/usr/bin/env bash
# Smoke test for S96: Inline Gap Analysis Card in Chat.
# Tests that the chat stream endpoint routes notes_gap intent to a __card__ SSE event.
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

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. Create a note
CREATE_RESP=$(curl -s -X POST "${BASE}/notes" \
  -H "Content-Type: application/json" \
  -d '{"content":"Alice fell down a rabbit hole","tags":[]}')
NOTE_ID=$(echo "$CREATE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

if [ -z "$NOTE_ID" ]; then
  echo "FAIL: POST /notes did not return an id"
  exit 1
fi

# 3. POST /qa with a notes_gap query and no document_id (scope=all).
#    Expect __card__ SSE event with an error field (no document selected).
STREAM_BODY='{"question":"find gaps in my notes","document_ids":[],"scope":"all","model":null}'

SSE_OUTPUT=$(curl -s -X POST "${BASE}/qa" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d "$STREAM_BODY" \
  --max-time 15)

if [ -z "$SSE_OUTPUT" ]; then
  echo "FAIL: /qa returned empty response"
  exit 1
fi

# Expect a "card" key in the SSE data
if echo "$SSE_OUTPUT" | grep -q '"card"'; then
  echo "PASS: S96 -- /qa emits card SSE event for notes_gap intent"
else
  echo "FAIL: /qa did not emit a card event for notes_gap query"
  echo "Response was:"
  echo "$SSE_OUTPUT"
  exit 1
fi
