#!/usr/bin/env bash
# Smoke test for S135: GET /graph/entities/{doc_id}?type=LIBRARY returns HTTP 200 and JSON.
# Requires the backend to be running on localhost:7820.
#
# Usage: ./scripts/smoke/S135.sh [document_id]
# If document_id is omitted, the test verifies the endpoint exists and returns 200
# with an empty entities array (no doc found — valid response).

set -euo pipefail

BASE="http://localhost:7820"
DOC_ID="${1:-smoke-test-nonexistent-doc}"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. GET /graph/entities/{doc_id}?type=LIBRARY — assert HTTP 200 and JSON with 'entities' key
TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -s -o "${TMPFILE}" -w "%{http_code}" \
  "${BASE}/graph/entities/${DOC_ID}?type=LIBRARY")

if [ "$HTTP_STATUS" != "200" ]; then
  echo "FAIL: GET /graph/entities/${DOC_ID}?type=LIBRARY returned HTTP ${HTTP_STATUS}"
  cat "${TMPFILE}"
  rm -f "${TMPFILE}"
  exit 1
fi

BODY=$(cat "${TMPFILE}")
rm -f "${TMPFILE}"

# Body must contain 'entities' key
if [[ "$BODY" != *'"entities"'* ]]; then
  echo "FAIL: response missing 'entities' key: ${BODY:0:200}"
  exit 1
fi

# 3. Verify the endpoint is NOT captured by the /{document_id} route
# (entities key in response, not graph nodes/edges)
if [[ "$BODY" == *'"nodes"'* ]] && [[ "$BODY" != *'"entities"'* ]]; then
  echo "FAIL: route shadowing detected -- got graph response instead of entity list"
  exit 1
fi

# 4. GET /graph/entities/{doc_id}?type=ALGORITHM — verify other types work too
TMPFILE2=$(mktemp)
HTTP_ALGO=$(curl -s -o "${TMPFILE2}" -w "%{http_code}" \
  "${BASE}/graph/entities/${DOC_ID}?type=ALGORITHM")
rm -f "${TMPFILE2}"

if [ "$HTTP_ALGO" != "200" ]; then
  echo "FAIL: GET /graph/entities/${DOC_ID}?type=ALGORITHM returned HTTP ${HTTP_ALGO}"
  exit 1
fi

echo "PASS: S135 -- GET /graph/entities endpoint returns HTTP 200 with JSON entities list"
