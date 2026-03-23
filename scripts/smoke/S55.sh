#!/usr/bin/env bash
# Smoke test for S55: cross-document holistic summary — POST /summarize/all
# returns 200 with text/event-stream; error event when < 2 docs ingested.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# POST /summarize/all should return 200 regardless of library state
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${BASE}/summarize/all" \
  -H "Content-Type: application/json" \
  -d '{"mode": "executive", "model": null}')

if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: POST /summarize/all returned ${HTTP_CODE} (expected 200)"
  exit 1
fi

# Verify the response is an SSE stream (text/event-stream content-type)
CONTENT_TYPE=$(curl -s -o /dev/null -w "%{content_type}" \
  -X POST "${BASE}/summarize/all" \
  -H "Content-Type: application/json" \
  -d '{"mode": "one_sentence", "model": null}')

if [[ "$CONTENT_TYPE" != *"text/event-stream"* ]]; then
  echo "FAIL: POST /summarize/all content-type is '${CONTENT_TYPE}' (expected text/event-stream)"
  exit 1
fi

echo "PASS: POST /summarize/all returns 200 with text/event-stream"
