#!/usr/bin/env bash
# Smoke test for S95: Smart Start suggestion pills.
# Verifies GET /study/due with a nonexistent document_id returns HTTP 200 and a JSON array.
# Requires the backend to be running on localhost:8000.

set -euo pipefail

BASE="http://localhost:8000"

# GET /study/due with a nonexistent document_id -- must return 200 and an array (empty is fine)
HTTP_CODE=$(curl -s -o /tmp/s95_due_resp.json -w "%{http_code}" \
  "${BASE}/study/due?document_id=nonexistent-doc-id")

if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: GET /study/due?document_id=nonexistent returned ${HTTP_CODE} (expected 200)"
  exit 1
fi

# Verify body is a JSON array
IS_ARRAY=$(python3 -c "import sys,json; d=json.load(open('/tmp/s95_due_resp.json')); print('yes' if isinstance(d, list) else 'no')")
if [ "$IS_ARRAY" != "yes" ]; then
  echo "FAIL: GET /study/due response is not a JSON array"
  exit 1
fi

echo "PASS: S95 -- GET /study/due returns 200 JSON array for nonexistent document_id"
