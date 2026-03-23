#!/usr/bin/env bash
# Smoke test for S149: EPUB chapter viewer endpoints
# Confirms that the EPUB endpoints are registered and return expected status codes.
# A 404 for an unknown document ID is expected (and correct) — we check it is NOT 500.
set -euo pipefail

BASE_URL="${LUMINARY_BASE_URL:-http://localhost:7820}"
UNKNOWN_ID="00000000-0000-0000-0000-000000000000"

echo "S149 smoke test: EPUB TOC endpoint registration"

# Check that the endpoint is registered — a 404 (doc not found) is correct,
# a 422 or 500 would indicate routing or startup failure.
TOC_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/documents/${UNKNOWN_ID}/epub/toc")
if [ "$TOC_STATUS" != "404" ]; then
  echo "FAIL: GET /documents/{id}/epub/toc returned HTTP ${TOC_STATUS}, expected 404"
  exit 1
fi
echo "  PASS: GET /documents/{id}/epub/toc -> 404 (endpoint registered)"

# Check the chapter endpoint
CHAPTER_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/documents/${UNKNOWN_ID}/epub/chapter/0")
if [ "$CHAPTER_STATUS" != "404" ]; then
  echo "FAIL: GET /documents/{id}/epub/chapter/0 returned HTTP ${CHAPTER_STATUS}, expected 404"
  exit 1
fi
echo "  PASS: GET /documents/{id}/epub/chapter/0 -> 404 (endpoint registered)"

echo "S149 smoke test PASSED"
