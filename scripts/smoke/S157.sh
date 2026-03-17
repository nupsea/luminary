#!/usr/bin/env bash
# Smoke test for S157 -- source citation chips with section_preview_snippet.
# Verifies that GET /qa/history returns a 200 response (chat QA endpoint is reachable).
# Full citation chip behaviour is tested in Vitest unit tests.
set -euo pipefail

BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  "${BASE}/qa/history?limit=1")

if [ "$STATUS" = "200" ]; then
  echo "S157 smoke: GET /qa/history returns 200 -- OK"
else
  echo "S157 smoke: expected 200, got $STATUS" >&2
  exit 1
fi

echo "S157 smoke PASSED"
