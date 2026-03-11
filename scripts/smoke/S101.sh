#!/usr/bin/env bash
# Smoke test for S101: GET /study/session-plan returns HTTP 200 with 'items' key.
# Requires the backend to be running on localhost:8000.

set -euo pipefail

BASE="http://localhost:8000"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. GET /study/session-plan?minutes=20 -- assert HTTP 200 and JSON has 'items' key
TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -s -o "${TMPFILE}" -w "%{http_code}" "${BASE}/study/session-plan?minutes=20")

if [ "$HTTP_STATUS" != "200" ]; then
  echo "FAIL: expected 200, got ${HTTP_STATUS}"
  cat "${TMPFILE}"
  rm -f "${TMPFILE}"
  exit 1
fi

BODY=$(cat "${TMPFILE}")
rm -f "${TMPFILE}"

# Body must contain "items" key
if [[ "$BODY" != *'"items"'* ]]; then
  echo "FAIL: expected JSON with 'items' key, got: ${BODY:0:80}"
  exit 1
fi

echo "PASS: S101 -- GET /study/session-plan returned HTTP 200 with 'items' key"
