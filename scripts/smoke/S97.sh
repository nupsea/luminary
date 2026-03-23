#!/usr/bin/env bash
# Smoke test for S97: POST /flashcards/from-gaps endpoint.
# Tests validation (422 on empty gaps) and that a non-empty request is accepted
# (200 if Ollama is running, 503 if not -- both are valid for this smoke test).
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. Empty gaps list should return 422
HTTP_EMPTY=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${BASE}/flashcards/from-gaps" \
  -H "Content-Type: application/json" \
  -d '{"gaps":[],"document_id":""}')

if [ "$HTTP_EMPTY" != "422" ]; then
  echo "FAIL: expected 422 for empty gaps, got ${HTTP_EMPTY}"
  exit 1
fi

# 3. Non-empty gaps list should return 200 (Ollama running) or 503 (Ollama offline) -- never 422/500
HTTP_GAP=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${BASE}/flashcards/from-gaps" \
  -H "Content-Type: application/json" \
  -d '{"gaps":["photosynthesis"],"document_id":""}')

if [ "$HTTP_GAP" != "200" ] && [ "$HTTP_GAP" != "503" ]; then
  echo "FAIL: expected 200 or 503 for non-empty gaps, got ${HTTP_GAP}"
  exit 1
fi

echo "PASS: S97 -- POST /flashcards/from-gaps validation and endpoint routing correct (gap call: ${HTTP_GAP})"
