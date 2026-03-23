#!/usr/bin/env bash
# Smoke test for S151: In-document Cmd+F search endpoint
# Verifies that GET /documents/{id}/search is reachable and returns expected responses.
set -euo pipefail

BASE="${API_BASE:-http://localhost:7820}"

echo "S151 smoke: GET /documents/nonexistent/search?q=hello returns 404"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/documents/nonexistent-doc-s151/search?q=hello")
[ "$STATUS" = "404" ] || { echo "FAIL: expected 404 got $STATUS"; exit 1; }

echo "S151 smoke: GET /documents/nonexistent/search?q= (empty) returns 200 with empty array"
BODY=$(curl -s "$BASE/documents/nonexistent-doc-s151/search?q=")
[ "$BODY" = "[]" ] || { echo "FAIL: expected [] got $BODY"; exit 1; }

echo "S151 smoke: PASS"
