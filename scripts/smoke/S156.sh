#!/usr/bin/env bash
# Smoke test for S156 -- structured rubric scoring for teachback and Feynman.
# Verifies that POST /study/teachback returns 404 for an unknown flashcard_id
# (i.e. the endpoint is reachable and returns the expected status for bad input).
set -euo pipefail

BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${BASE}/study/teachback" \
  -H "Content-Type: application/json" \
  -d '{"flashcard_id": "nonexistent-id-s156", "user_explanation": "test"}')

if [ "$STATUS" = "404" ]; then
  echo "S156 smoke: POST /study/teachback returns 404 for unknown flashcard_id -- OK"
else
  echo "S156 smoke: expected 404, got $STATUS" >&2
  exit 1
fi

echo "S156 smoke PASSED"
