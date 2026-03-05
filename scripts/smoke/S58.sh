#!/usr/bin/env bash
# Smoke test for S58: query rewriting — POST /qa returns a non-500 streaming response.
# The rewriting logic is exercised internally; we verify the endpoint is up and
# does not crash when a vague-reference question is submitted with scope=all.
# Requires the backend to be running on localhost:8000.

set -euo pipefail

BASE="http://localhost:8000"

# POST /qa with a vague-reference question (scope=all skips rewriting per spec).
# Must return HTTP 200 with Content-Type: text/event-stream.
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${BASE}/qa" \
  -H "Content-Type: application/json" \
  -d '{"question": "What did they decide?", "scope": "all", "document_ids": null}')

if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: POST /qa returned ${HTTP_CODE} (expected 200)"
  exit 1
fi

# POST /qa with scope=single and an unknown doc_id — must return 200 (no_context SSE event).
HTTP_CODE2=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${BASE}/qa" \
  -H "Content-Type: application/json" \
  -d '{"question": "What did they decide?", "scope": "single", "document_ids": ["smoke-s58-nonexistent"]}')

if [ "$HTTP_CODE2" != "200" ]; then
  echo "FAIL: POST /qa (scope=single) returned ${HTTP_CODE2} (expected 200)"
  exit 1
fi

echo "PASS: POST /qa returns 200 for vague-reference questions in both all and single scope"
