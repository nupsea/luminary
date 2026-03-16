#!/usr/bin/env bash
# Smoke test for S98: POST /qa/stream with 'quiz me' question returns HTTP 200.
# The response is an SSE stream; we just assert HTTP 200 and non-empty body.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. POST /qa with 'quiz me' question -- assert HTTP 200 and non-empty SSE body
TMPFILE=$(mktemp)
HTTP_QUIZ=$(curl -s -o "${TMPFILE}" -w "%{http_code}" \
  -X POST "${BASE}/qa" \
  -H "Content-Type: application/json" \
  -d '{"question":"quiz me","document_ids":[],"scope":"all"}')

if [ "$HTTP_QUIZ" != "200" ]; then
  echo "FAIL: expected 200 for quiz me, got ${HTTP_QUIZ}"
  rm -f "${TMPFILE}"
  exit 1
fi

BODY_SIZE=$(wc -c < "${TMPFILE}")
rm -f "${TMPFILE}"

if [ "$BODY_SIZE" -lt 5 ]; then
  echo "FAIL: expected non-empty SSE body, got ${BODY_SIZE} bytes"
  exit 1
fi

echo "PASS: S98 -- POST /qa with 'quiz me' returned HTTP 200 (body size: ${BODY_SIZE} bytes)"
