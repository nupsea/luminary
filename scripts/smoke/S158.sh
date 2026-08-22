#!/usr/bin/env bash
# Smoke test for S158 -- retrieval transparency panel (confidence badge + How I Answered).
# Verifies that GET /qa/history returns HTTP 200 (QA endpoint reachable).
# Transparency SSE event behaviour is covered by backend unit tests.
set -euo pipefail

BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"

# `GET /qa/history` is gone: conversation history moved into the request
# (`QARequest.messages`, a sliding window the client owns), so there is no
# server-side history to fetch. What this script actually asserted was that the
# QA surface is mounted, which an invalid body proves without spending a
# model call.
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${BASE}/qa" -H 'Content-Type: application/json' -d '{}')

if [ "$STATUS" = "422" ]; then
  echo "S158 smoke: POST /qa is mounted and validating -- OK"
else
  echo "S158 smoke: expected 422 from an empty /qa body, got $STATUS" >&2
  exit 1
fi

echo "S158 smoke PASSED"
