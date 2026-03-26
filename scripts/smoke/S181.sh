#!/usr/bin/env bash
# Smoke test for S181: Viz tab overhaul
# Verifies the backend endpoints used by the Viz tab still respond correctly.
set -euo pipefail

BASE="${LUMINARY_API:-http://localhost:8000}"
PASS=0
FAIL=0

check() {
  local desc="$1"
  local url="$2"
  local expected_field="$3"
  local http_status
  local body

  local raw
  raw=$(curl -s -w "\n%{http_code}" "$url")
  http_status=$(echo "$raw" | tail -1)
  body=$(echo "$raw" | sed '$d')

  if [[ "$http_status" != "200" ]]; then
    echo "FAIL [$desc] -- HTTP $http_status for $url"
    FAIL=$((FAIL + 1))
    return
  fi

  if ! echo "$body" | python3 -c "import sys, json; d=json.load(sys.stdin); assert '$expected_field' in str(d)" 2>/dev/null; then
    echo "FAIL [$desc] -- field '$expected_field' not found in response"
    FAIL=$((FAIL + 1))
    return
  fi

  echo "PASS [$desc]"
  PASS=$((PASS + 1))
}

# Documents list endpoint (used by Viz fetchDocList)
check \
  "GET /documents returns items list" \
  "${BASE}/documents?sort=newest&page=1&page_size=1" \
  "items"

# Global knowledge graph endpoint (no doc_ids = empty graph is valid, must return 200)
check \
  "GET /graph with no doc_ids returns nodes/edges" \
  "${BASE}/graph?doc_ids=" \
  "nodes"

# Tag graph endpoint (used by Tags mode in Viz)
check \
  "GET /tags/graph returns nodes/edges" \
  "${BASE}/tags/graph" \
  "nodes"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
