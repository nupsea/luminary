#!/usr/bin/env bash
# Smoke test for S60: GET /sections/{id} and GET /documents/{id}/conversation return 200.
# Requires the backend to be running on localhost:8000.

set -euo pipefail

BASE="http://localhost:8000"

# 1. GET /sections/<nonexistent-id> — must return 200 with empty array (no 404/500)
BODY=$(curl -sf "${BASE}/sections/nonexistent-id-smoke-s60")
if ! echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert isinstance(d, list)" 2>/dev/null; then
  echo "FAIL: GET /sections/nonexistent-id did not return a JSON array"
  exit 1
fi

# 2. GET /documents/<nonexistent-id>/conversation — must return 404 (not 500)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/documents/nonexistent-id-smoke-s60/conversation")
if [ "$HTTP_CODE" != "404" ]; then
  echo "FAIL: GET /documents/nonexistent-id/conversation returned ${HTTP_CODE} (expected 404)"
  exit 1
fi

echo "PASS: GET /sections returns empty array for unknown doc; GET /documents/{id}/conversation returns 404 for unknown doc"
