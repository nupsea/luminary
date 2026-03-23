#!/usr/bin/env bash
# Smoke test for S130: RAGAS eval per-book breakdown
# Calls GET /evals/results and asserts HTTP 200 with a non-empty JSON array.
#
# Usage: bash scripts/smoke/S130.sh
# Prerequisites: backend running on localhost:7820

set -euo pipefail

BASE_URL="${LUMINARY_BACKEND_URL:-http://localhost:7820}"

echo "S130 smoke: GET /evals/results"

response=$(curl -s -w "\n%{http_code}" "${BASE_URL}/evals/results")
http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | head -n -1)

if [ "$http_code" != "200" ]; then
  echo "FAIL: expected HTTP 200, got $http_code"
  echo "Body: $body"
  exit 1
fi

# Assert response is a non-empty JSON array (at least one result row)
count=$(echo "$body" | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data))")
if [ "$count" -lt 1 ]; then
  echo "FAIL: expected at least 1 result row, got $count"
  echo "Body: $body"
  exit 1
fi

echo "PASS: /evals/results returned HTTP 200 with $count result row(s)"
