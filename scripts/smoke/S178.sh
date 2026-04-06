#!/usr/bin/env bash
# Smoke test for S178: Study tab consolidation.
# Verifies that the flashcard and deck endpoints used by the Study tab
# (SmartGeneratePanel + DeckStatusAccordion) still respond correctly.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. GET /flashcards/decks -- used by All Decks panel
HTTP_DECKS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/flashcards/decks")
if [ "$HTTP_DECKS" != "200" ]; then
  echo "FAIL: GET /flashcards/decks returned ${HTTP_DECKS}, expected 200"
  exit 1
fi

# 3. GET /flashcards/health/{doc_id} -- used by DeckStatusAccordion (HealthReportPanel half)
# Use a fake doc_id; expect 200 with zero counts (not 404/500)
HTTP_HEALTH_REPORT=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/flashcards/health/smoke-test-doc")
if [ "$HTTP_HEALTH_REPORT" != "200" ]; then
  echo "FAIL: GET /flashcards/health/smoke-test-doc returned ${HTTP_HEALTH_REPORT}, expected 200"
  exit 1
fi

# 4. GET /flashcards/audit/{doc_id} -- used by DeckStatusAccordion (DeckHealthPanel half)
HTTP_AUDIT=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/flashcards/audit/smoke-test-doc")
if [ "$HTTP_AUDIT" != "200" ]; then
  echo "FAIL: GET /flashcards/audit/smoke-test-doc returned ${HTTP_AUDIT}, expected 200"
  exit 1
fi

echo "PASS: S178 -- flashcard decks, health, and audit endpoints all returned 200"
