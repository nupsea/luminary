#!/usr/bin/env bash
# S109 smoke: GET /chat/explorations returns HTTP 200 JSON array
# Uses a nonexistent doc_id -- graceful empty response is the expected result.
set -euo pipefail

BASE="http://localhost:7820"

echo "S109 [1/2]: GET /chat/explorations with unknown doc returns 200 empty list..."
RESP=$(curl -sf "${BASE}/chat/explorations?document_id=smoke-nonexistent-doc-s109")
echo "$RESP" | python3 -c "import sys, json; data=json.load(sys.stdin); assert isinstance(data, list), 'Expected list'" \
  || { echo "FAIL: response is not a JSON array"; exit 1; }
echo "PASS: returns JSON array"

echo "S109 [2/2]: TypeScript type check..."
cd "$(dirname "$0")/../../frontend"
# tsconfig.json is solution-style ("files": []), so a bare `tsc --noEmit`
# resolves zero files and exits 0 with real type errors present -- measured.
# `-b` walks the project references; the project binary, not npx, is the
# compiler this repo pins.
./node_modules/.bin/tsc -b --noEmit --force
echo "PASS: tsc --noEmit"

echo "S109: ALL CHECKS PASSED"
