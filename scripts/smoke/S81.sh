#!/usr/bin/env bash
# S81 smoke test: confidence-adaptive retry
# Tests that POST /qa returns HTTP 200 for each intent type with retry mocked.
#
# Usage: ./scripts/smoke/S81.sh [BASE_URL]
# Requires: backend running at BASE_URL (default http://localhost:7820)

set -euo pipefail

BASE="${1:-http://localhost:7820}"

echo "S81 smoke: confidence-adaptive retry — $BASE"

# Helper: check HTTP status and done event
check_qa() {
    local desc="$1"
    local payload="$2"
    local resp
    resp=$(curl -sf -X POST "$BASE/qa" \
        -H "Content-Type: application/json" \
        -d "$payload" 2>&1) || { echo "FAIL [$desc]: curl error"; return 1; }

    if echo "$resp" | grep -q '"done":true'; then
        echo "PASS [$desc]"
    else
        echo "FAIL [$desc]: no done event in response"
        echo "  Response: ${resp:0:300}"
        return 1
    fi
}

# Test 1: factual question (search_node path, may trigger retry on low confidence)
check_qa "factual (search)" \
    '{"question": "Who is the main character?", "document_ids": [], "scope": "all"}'

# Test 2: summary question
check_qa "summary" \
    '{"question": "Please summarize this document", "document_ids": [], "scope": "all"}'

# Test 3: comparative question
check_qa "comparative" \
    '{"question": "Compare Alice versus Odysseus", "document_ids": [], "scope": "all"}'

# Test 4: relational question
check_qa "relational" \
    '{"question": "How are Odysseus and Telemachus related?", "document_ids": [], "scope": "all"}'

echo ""
echo "S81 smoke: all checks passed"
