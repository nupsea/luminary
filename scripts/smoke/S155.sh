#!/usr/bin/env bash
set -euo pipefail
BASE="http://localhost:7820"

# Test that the endpoint exists and returns 404 for a non-existent card
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  "${BASE}/flashcards/nonexistent-card-id/source-context")
[ "$STATUS" = "404" ] && echo "S155 smoke: 404 for unknown card_id -- OK" \
  || (echo "S155 smoke: expected 404 got $STATUS" && exit 1)

echo "S155 smoke PASSED"
