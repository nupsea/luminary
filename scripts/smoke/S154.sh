#!/usr/bin/env bash
# Smoke test for S154: POST /flashcards/cloze/{section_id}
# Requires the backend to be running on localhost:7820.
#
# Exit 0 = PASS, Exit 1 = FAIL

set -euo pipefail

BASE="http://localhost:7820"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. POST /flashcards/cloze/nonexistent-section?count=1
# Expect 201 (empty list -- section has no chunks) or 503 (Ollama offline).
# Either way the endpoint must exist and NOT return 404 or 500.
HTTP_CLOZE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${BASE}/flashcards/cloze/nonexistent-section?count=1")

if [ "$HTTP_CLOZE" = "404" ] || [ "$HTTP_CLOZE" = "500" ]; then
  echo "FAIL: /flashcards/cloze endpoint returned ${HTTP_CLOZE} (expected 201 or 503)"
  exit 1
fi

echo "PASS: S154 -- POST /flashcards/cloze endpoint exists (HTTP ${HTTP_CLOZE})"
