#!/usr/bin/env bash
# Smoke test for S131: code-aware chunking endpoint
# Calls GET /documents/nonexistent-id/code_snippets and asserts HTTP 404.
#
# Usage: bash scripts/smoke/S131.sh
# Prerequisites: backend running on localhost:7820

set -euo pipefail
source "$(dirname "$0")/lib.sh"

echo "S131 smoke: GET /documents/nonexistent-id/code_snippets expects 404"

http_code=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/documents/nonexistent-id/code_snippets")

if [ "$http_code" != "404" ]; then
  echo "FAIL: expected HTTP 404 for nonexistent document, got $http_code"
  exit 1
fi

echo "PASS: /documents/nonexistent-id/code_snippets returned HTTP 404 as expected"
