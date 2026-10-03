#!/usr/bin/env bash
# Smoke test for S130: RAGAS eval per-book breakdown
# Calls GET /evals/results and asserts every row names its dataset and run time.
# The rows come from evals/scores_history.jsonl in the checkout; with none, it skips.
#
# Usage: bash scripts/smoke/S130.sh
# Prerequisites: backend running on localhost:7820

set -euo pipefail
source "$(dirname "$0")/lib.sh"
smoke_require_mode full

echo "S130 smoke: GET /evals/results"

response=$(curl -s -w "\n%{http_code}" "${BASE}/evals/results")
http_code=$(echo "$response" | tail -1)
# `head -n -1` is GNU-only and errors on macOS; sed drops the last line portably.
body=$(echo "$response" | sed '$d')

if [ "$http_code" != "200" ]; then
  echo "FAIL: expected HTTP 200, got $http_code"
  echo "Body: $body"
  exit 1
fi

count=$(echo "$body" | python3 -c "import sys, json; print(len(json.load(sys.stdin)))")
if [ "$count" -lt 1 ]; then
  echo "SKIP: no eval has run in this checkout, so there are no rows to check"
  exit "$SMOKE_SKIP"
fi

bad=$(echo "$body" | python3 -c "
import sys, json
rows = json.load(sys.stdin)
print(sum(1 for r in rows if not r.get('dataset') or not r.get('run_at')))")
if [ "$bad" -ne 0 ]; then
  echo "FAIL: $bad of $count rows lack a dataset or run_at"
  echo "Body: $body"
  exit 1
fi

echo "PASS: /evals/results returned $count row(s), each with a dataset and run time"
