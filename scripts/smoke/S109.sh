#!/usr/bin/env bash
# S109 smoke: GET /chat/explorations returns HTTP 200 JSON array
# Uses a nonexistent doc_id -- graceful empty response is the expected result.
set -euo pipefail

BASE="http://localhost:8000"

echo "S109 [1/2]: GET /chat/explorations with unknown doc returns 200 empty list..."
RESP=$(curl -sf "${BASE}/chat/explorations?document_id=smoke-nonexistent-doc-s109")
echo "$RESP" | python3 -c "import sys, json; data=json.load(sys.stdin); assert isinstance(data, list), 'Expected list'" \
  || { echo "FAIL: response is not a JSON array"; exit 1; }
echo "PASS: returns JSON array"

echo "S109 [2/2]: TypeScript type check..."
cd "$(dirname "$0")/../../frontend"
npx tsc --noEmit
echo "PASS: tsc --noEmit"

echo "S109: ALL CHECKS PASSED"
