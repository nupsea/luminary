#!/usr/bin/env bash
# Smoke test for S67: Library list view — chunk_count in GET /documents
set -euo pipefail

BASE="http://localhost:8000"

echo "S67 smoke: GET /documents returns 200 with chunk_count field"
RESP=$(curl -sf "${BASE}/documents")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/documents")
if [ "$STATUS" != "200" ]; then
  echo "FAIL: GET /documents returned HTTP $STATUS"
  exit 1
fi
if ! echo "$RESP" | grep -q "chunk_count"; then
  echo "FAIL: Response does not contain 'chunk_count'"
  exit 1
fi
echo "PASS: GET /documents returns 200 and includes chunk_count"
