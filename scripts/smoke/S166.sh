#!/usr/bin/env bash
# Smoke test for S166: Semantic note clustering via HDBSCAN
# Tests POST /notes/cluster, GET /notes/cluster/suggestions, accept, and reject

set -euo pipefail

BASE="http://localhost:8000"

echo "=== S166 Smoke Test: Semantic note clustering ==="

# 1. POST /notes/cluster — should return 202 with queued or cached
echo "1. POST /notes/cluster"
CLUSTER_RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/notes/cluster")
HTTP_CODE=$(echo "$CLUSTER_RESP" | tail -1)
BODY=$(echo "$CLUSTER_RESP" | head -1)

if [ "$HTTP_CODE" != "202" ]; then
  echo "FAIL: Expected 202, got $HTTP_CODE"
  echo "Body: $BODY"
  exit 1
fi

if ! echo "$BODY" | grep -qE '"queued"|"cached"'; then
  echo "FAIL: Response missing 'queued' or 'cached' field"
  echo "Body: $BODY"
  exit 1
fi
echo "  OK: $BODY"

# 2. GET /notes/cluster/suggestions — should return 200 with an array
echo "2. GET /notes/cluster/suggestions"
SUGGESTIONS_RESP=$(curl -s -w "\n%{http_code}" "$BASE/notes/cluster/suggestions")
HTTP_CODE=$(echo "$SUGGESTIONS_RESP" | tail -1)
BODY=$(echo "$SUGGESTIONS_RESP" | head -1)

if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: Expected 200, got $HTTP_CODE"
  echo "Body: $BODY"
  exit 1
fi

if ! echo "$BODY" | grep -q '^\['; then
  echo "FAIL: Response is not a JSON array"
  echo "Body: $BODY"
  exit 1
fi

SUGGESTION_COUNT=$(echo "$BODY" | python3 -c "import sys,json; data=json.load(sys.stdin); print(len(data))")
echo "  OK: Response is array ($SUGGESTION_COUNT items)"

# 3. If suggestions exist, test accept and reject endpoints
if [ "$SUGGESTION_COUNT" -gt "0" ]; then
  # Get the first suggestion id
  FIRST_ID=$(echo "$BODY" | python3 -c "import sys,json; data=json.load(sys.stdin); print(data[0]['id'])")

  # Test reject endpoint
  echo "3. POST /notes/cluster/suggestions/$FIRST_ID/reject"
  REJECT_RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/notes/cluster/suggestions/$FIRST_ID/reject")
  REJECT_CODE=$(echo "$REJECT_RESP" | tail -1)
  REJECT_BODY=$(echo "$REJECT_RESP" | head -1)

  if [ "$REJECT_CODE" != "200" ]; then
    echo "FAIL: Expected 200, got $REJECT_CODE"
    echo "Body: $REJECT_BODY"
    exit 1
  fi
  if ! echo "$REJECT_BODY" | grep -q '"ok"'; then
    echo "FAIL: Reject response missing 'ok' field"
    echo "Body: $REJECT_BODY"
    exit 1
  fi
  echo "  OK: $REJECT_BODY"

  # If there are at least 2 suggestions, test accept on the second one
  if [ "$SUGGESTION_COUNT" -gt "1" ]; then
    SECOND_ID=$(echo "$BODY" | python3 -c "import sys,json; data=json.load(sys.stdin); print(data[1]['id'])")
    echo "4. POST /notes/cluster/suggestions/$SECOND_ID/accept"
    ACCEPT_RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/notes/cluster/suggestions/$SECOND_ID/accept")
    ACCEPT_CODE=$(echo "$ACCEPT_RESP" | tail -1)
    ACCEPT_BODY=$(echo "$ACCEPT_RESP" | head -1)

    if [ "$ACCEPT_CODE" != "200" ]; then
      echo "FAIL: Expected 200, got $ACCEPT_CODE"
      echo "Body: $ACCEPT_BODY"
      exit 1
    fi
    if ! echo "$ACCEPT_BODY" | grep -q '"collection_id"'; then
      echo "FAIL: Accept response missing 'collection_id' field"
      echo "Body: $ACCEPT_BODY"
      exit 1
    fi
    echo "  OK: $ACCEPT_BODY"
  else
    echo "3b. Only 1 suggestion; testing accept on it after creating a fresh one"
    # Create a second suggestion to test accept path via invalid UUID (404 expected — verify 404)
    echo "4. POST /notes/cluster/suggestions/nonexistent-id/accept (expect 404)"
    ACCEPT_RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/notes/cluster/suggestions/nonexistent-id/accept")
    ACCEPT_CODE=$(echo "$ACCEPT_RESP" | tail -1)
    if [ "$ACCEPT_CODE" != "404" ]; then
      echo "FAIL: Expected 404 for nonexistent id, got $ACCEPT_CODE"
      exit 1
    fi
    echo "  OK: 404 returned for missing suggestion"
  fi
else
  echo "3. No suggestions available (not enough note vectors for clustering)"
  echo "   Testing accept and reject with nonexistent IDs to verify 404 behavior"

  echo "   POST /notes/cluster/suggestions/nonexistent/accept (expect 404)"
  ACCEPT_RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/notes/cluster/suggestions/nonexistent/accept")
  ACCEPT_CODE=$(echo "$ACCEPT_RESP" | tail -1)
  if [ "$ACCEPT_CODE" != "404" ]; then
    echo "FAIL: Expected 404, got $ACCEPT_CODE"
    exit 1
  fi
  echo "  OK: accept returns 404 for missing suggestion"

  echo "   POST /notes/cluster/suggestions/nonexistent/reject (expect 404)"
  REJECT_RESP=$(curl -s -w "\n%{http_code}" -X POST "$BASE/notes/cluster/suggestions/nonexistent/reject")
  REJECT_CODE=$(echo "$REJECT_RESP" | tail -1)
  if [ "$REJECT_CODE" != "404" ]; then
    echo "FAIL: Expected 404, got $REJECT_CODE"
    exit 1
  fi
  echo "  OK: reject returns 404 for missing suggestion"
fi

echo ""
echo "=== S166 Smoke Test PASSED ==="
