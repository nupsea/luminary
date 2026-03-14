#!/usr/bin/env bash
set -e
BASE=http://localhost:8000

# Verify the library endpoint returns expected shape
RESP=$(curl -sf "${BASE}/documents")
echo "${RESP}" | grep -q '"items"' || { echo "FAIL: /documents did not return items"; exit 1; }

# Verify audio content_type filter is accepted (no 422 or 500)
FILTER_RESP=$(curl -sf "${BASE}/documents?content_type=audio")
echo "${FILTER_RESP}" | grep -q '"items"' || { echo "FAIL: audio filter rejected"; exit 1; }

echo "S119 smoke: PASS"
