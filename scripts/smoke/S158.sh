#!/usr/bin/env bash
# Smoke test for S158 -- retrieval transparency panel (confidence badge + How I Answered).
# Verifies that GET /qa/history returns HTTP 200 (QA endpoint reachable).
# Transparency SSE event behaviour is covered by backend unit tests.
set -euo pipefail

BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  "${BASE}/qa/history?limit=1")

if [ "$STATUS" = "200" ]; then
  echo "S158 smoke: GET /qa/history returns 200 -- OK"
else
  echo "S158 smoke: expected 200, got $STATUS" >&2
  exit 1
fi

echo "S158 smoke PASSED"
