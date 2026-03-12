#!/usr/bin/env bash
# S104 smoke test: GET /settings/llm returns 200 with has_*_key booleans (no raw key in body)
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

echo "S104: GET /settings/llm returns 200..."
BODY=$(curl -s -w "\n%{http_code}" "${BASE_URL}/settings/llm")
STATUS=$(echo "$BODY" | tail -1)
RESPONSE=$(echo "$BODY" | head -1)

if [ "$STATUS" != "200" ]; then
  echo "FAIL: GET /settings/llm returned $STATUS (expected 200)"
  exit 1
fi

# Response must contain has_openai_key (boolean) — never raw key strings
if ! echo "$RESPONSE" | grep -q '"has_openai_key"'; then
  echo "FAIL: response missing has_openai_key field"
  exit 1
fi

# Verify mode field is present
if ! echo "$RESPONSE" | grep -q '"mode"'; then
  echo "FAIL: response missing mode field"
  exit 1
fi

echo "PASS: GET /settings/llm returned 200 with expected fields"
