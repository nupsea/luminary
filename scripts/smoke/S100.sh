#!/usr/bin/env bash
# Smoke test for S100: GET /chat/confusion-signals returns HTTP 200 and a JSON array.
# Requires the backend to be running on localhost:8000.

set -euo pipefail

BASE="http://localhost:8000"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. GET /chat/confusion-signals -- assert HTTP 200 and JSON array body
TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -s -o "${TMPFILE}" -w "%{http_code}" "${BASE}/chat/confusion-signals")

if [ "$HTTP_STATUS" != "200" ]; then
  echo "FAIL: expected 200, got ${HTTP_STATUS}"
  rm -f "${TMPFILE}"
  exit 1
fi

BODY=$(cat "${TMPFILE}")
rm -f "${TMPFILE}"

# Body must start with '[' (JSON array)
if [[ "$BODY" != \[* ]]; then
  echo "FAIL: expected JSON array body, got: ${BODY:0:80}"
  exit 1
fi

echo "PASS: S100 -- GET /chat/confusion-signals returned HTTP 200 with JSON array"
