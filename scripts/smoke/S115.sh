#!/usr/bin/env bash
# Smoke test for S115: Study session analytics
# Calls GET /study/sessions and asserts HTTP 200 with a non-empty body.
set -euo pipefail

BASE="http://localhost:8000"

echo "S115 smoke: GET /study/sessions"
RESPONSE=$(curl -sf -w "\n%{http_code}" "${BASE}/study/sessions?page=1&page_size=5")
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

echo "PASS: GET /study/sessions returned 200 with body"
echo "$BODY" | python3 -c "import sys, json; d = json.load(sys.stdin); print('total sessions:', d['total'])"
