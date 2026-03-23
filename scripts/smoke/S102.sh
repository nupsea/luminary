#!/usr/bin/env bash
# Smoke test for S102: tech debt - datetime.now(UTC), FK pragma, settings PATCH validation.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. GET /settings/llm -- assert HTTP 200
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/settings/llm")
if [ "$HTTP_STATUS" != "200" ]; then
  echo "FAIL: GET /settings/llm expected 200, got ${HTTP_STATUS}"
  exit 1
fi

# 3. PATCH /settings/llm with unknown field -- assert HTTP 422 (extra='forbid')
TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -s -o "${TMPFILE}" -w "%{http_code}" \
  -X PATCH "${BASE}/settings/llm" \
  -H "Content-Type: application/json" \
  -d '{"rogue_field": "x"}')

if [ "$HTTP_STATUS" != "422" ]; then
  echo "FAIL: PATCH /settings/llm with unknown field expected 422, got ${HTTP_STATUS}"
  cat "${TMPFILE}"
  rm -f "${TMPFILE}"
  exit 1
fi
rm -f "${TMPFILE}"

echo "PASS: S102 -- settings 200, unknown-field PATCH returns 422"
