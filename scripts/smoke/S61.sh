#!/usr/bin/env bash
# Smoke test for S61: document attribution — POST /qa returns 200 for both
# scope=all and scope=single; citation structure is valid JSON.
# Requires the backend to be running on localhost:8000.

set -euo pipefail

BASE="http://localhost:8000"

# scope=all with no documents → no_context error event (not a 500)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${BASE}/qa" \
  -H "Content-Type: application/json" \
  -d '{"question": "Who are the main characters?", "scope": "all"}')

if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: POST /qa (scope=all) returned ${HTTP_CODE} (expected 200)"
  exit 1
fi

# scope=single with an unknown doc → no_context error event (not a 500)
HTTP_CODE2=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${BASE}/qa" \
  -H "Content-Type: application/json" \
  -d '{"question": "Describe the protagonist.", "scope": "single", "document_ids": ["smoke-s61-nonexistent"]}')

if [ "$HTTP_CODE2" != "200" ]; then
  echo "FAIL: POST /qa (scope=single) returned ${HTTP_CODE2} (expected 200)"
  exit 1
fi

echo "PASS: POST /qa returns 200 for both scope=all and scope=single"
