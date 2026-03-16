#!/usr/bin/env bash
# Smoke test for S99: POST /qa with 'let me explain' question returns HTTP 200.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. POST /qa with teach_back phrase -- assert HTTP 200 and non-empty SSE body
TMPFILE=$(mktemp)
HTTP_TEACH=$(curl -s -o "${TMPFILE}" -w "%{http_code}" \
  -X POST "${BASE}/qa" \
  -H "Content-Type: application/json" \
  -d '{"question":"let me explain what I understand about this topic","document_ids":[],"scope":"all"}')

if [ "$HTTP_TEACH" != "200" ]; then
  echo "FAIL: expected 200 for teach_back question, got ${HTTP_TEACH}"
  rm -f "${TMPFILE}"
  exit 1
fi

BODY_SIZE=$(wc -c < "${TMPFILE}")
rm -f "${TMPFILE}"

if [ "$BODY_SIZE" -lt 5 ]; then
  echo "FAIL: expected non-empty SSE body, got ${BODY_SIZE} bytes"
  exit 1
fi

echo "PASS: S99 -- POST /qa with teach_back phrase returned HTTP 200 (body size: ${BODY_SIZE} bytes)"
