#!/usr/bin/env bash
# Smoke test for S116: FSRS fragility heatmap
# Calls GET /study/section-heatmap with a nonexistent document_id.
# Endpoint must return HTTP 200 with {"heatmap": {}}.
set -euo pipefail

BASE="http://localhost:7820"
DOC_ID="smoke-test-nonexistent"

echo "S116 smoke: GET /study/section-heatmap?document_id=${DOC_ID}"
RESPONSE=$(curl -sf -w "\n%{http_code}" "${BASE}/study/section-heatmap?document_id=${DOC_ID}")
BODY=$(echo "$RESPONSE" | head -n -1)
STATUS=$(echo "$RESPONSE" | tail -n 1)

if [ "$STATUS" != "200" ]; then
  echo "FAIL: expected 200, got $STATUS"
  exit 1
fi

if [ -z "$BODY" ]; then
  echo "FAIL: response body is empty"
  exit 1
fi

echo "PASS: GET /study/section-heatmap returned 200"
echo "$BODY" | python3 -c "import sys, json; d = json.load(sys.stdin); assert 'heatmap' in d, 'missing heatmap key'; print('heatmap keys:', len(d['heatmap']))"
