#!/usr/bin/env bash
# Smoke test for S185: Simplified Study tab
# Verifies backend endpoints used by InsightsAccordion are reachable.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"
DUMMY_DOC="smoke-doc-s185"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi
echo "PASS: health check"

# 2. Flashcard search endpoint (card list primary content)
HTTP_SEARCH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/flashcards/search?page=1&page_size=5")
if [ "$HTTP_SEARCH" != "200" ]; then
  echo "FAIL: GET /flashcards/search expected 200, got ${HTTP_SEARCH}"
  exit 1
fi
echo "PASS: flashcard search"

# 3. Bloom audit endpoint (InsightsAccordion -- bloom_audit section)
HTTP_AUDIT=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/flashcards/audit/${DUMMY_DOC}")
if [ "$HTTP_AUDIT" != "200" ] && [ "$HTTP_AUDIT" != "404" ]; then
  echo "FAIL: GET /flashcards/audit expected 200 or 404, got ${HTTP_AUDIT}"
  exit 1
fi
echo "PASS: bloom audit endpoint reachable (${HTTP_AUDIT})"

# 4. Health report endpoint (InsightsAccordion -- health_report section)
HTTP_HLTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/flashcards/health/${DUMMY_DOC}")
if [ "$HTTP_HLTH" != "200" ] && [ "$HTTP_HLTH" != "404" ]; then
  echo "FAIL: GET /flashcards/health expected 200 or 404, got ${HTTP_HLTH}"
  exit 1
fi
echo "PASS: health report endpoint reachable (${HTTP_HLTH})"

# 5. Struggling cards endpoint (InsightsAccordion -- struggling section)
HTTP_STRUG=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/study/struggling?document_id=${DUMMY_DOC}")
if [ "$HTTP_STRUG" != "200" ] && [ "$HTTP_STRUG" != "404" ]; then
  echo "FAIL: GET /study/struggling expected 200 or 404, got ${HTTP_STRUG}"
  exit 1
fi
echo "PASS: struggling endpoint reachable (${HTTP_STRUG})"

echo ""
echo "S185 smoke: ALL PASS"
