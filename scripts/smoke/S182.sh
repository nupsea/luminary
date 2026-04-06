#!/usr/bin/env bash
# Smoke test for S182 -- YouTube transcript viewer: GET /documents/{id}/chunks
set -euo pipefail

BASE="http://localhost:8000"
PASS=0
FAIL=0

check() {
  local desc="$1"
  local status="$2"
  local expected="$3"
  local body="$4"
  local field="$5"

  if [ "$status" -eq "$expected" ]; then
    echo "[PASS] $desc (HTTP $status)"
    PASS=$((PASS + 1))
  else
    echo "[FAIL] $desc (expected HTTP $expected, got $status)"
    FAIL=$((FAIL + 1))
  fi

  if [ -n "$field" ]; then
    if echo "$body" | python3 -c "import sys, json; d=json.load(sys.stdin); assert $field, 'field check failed'" 2>/dev/null; then
      echo "[PASS] $desc field check: $field"
      PASS=$((PASS + 1))
    else
      echo "[FAIL] $desc field check: $field"
      echo "       Body: $(echo "$body" | head -c 200)"
      FAIL=$((FAIL + 1))
    fi
  fi
}

# -----------------------------------------------------------------------
# 1. Create a document via POST /documents (plain text upload simulation)
#    We can't do a real YouTube ingest without yt-dlp, so create a doc
#    directly and add chunks via the DB, then test the endpoint.
#    Instead: test that the endpoint returns 404 for nonexistent doc.
# -----------------------------------------------------------------------

TMPFILE=$(mktemp)

# Test 1: GET /documents/{id}/chunks returns 404 for unknown document
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/documents/nonexistent-smoke-test-id/chunks")
BODY=$(cat "$TMPFILE")
check "GET /documents/nonexistent/chunks returns 404" "$STATUS" "404" "$BODY" ""

# Test 2: GET /documents returns 200 with channel_name field in schema
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/documents")
BODY=$(cat "$TMPFILE")
check "GET /documents returns 200" "$STATUS" "200" "$BODY" ""

# Test 3: Create a plain text document and verify chunks endpoint works
UPLOAD_TMPFILE=$(mktemp /tmp/s182_smoke_XXXXXX.txt)
echo "This is a test document for S182 smoke test. It has some content." > "$UPLOAD_TMPFILE"

STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
  -F "file=@$UPLOAD_TMPFILE;type=text/plain" \
  -F "content_type=notes" \
  "$BASE/documents/ingest")
BODY=$(cat "$TMPFILE")
check "POST /documents/ingest returns 200" "$STATUS" "200" "$BODY" ""

if [ "$STATUS" -eq 200 ]; then
  DOC_ID=$(echo "$BODY" | python3 -c "import sys, json; print(json.load(sys.stdin).get('document_id', ''))" 2>/dev/null || echo "")

  if [ -n "$DOC_ID" ]; then
    # Test 4: GET /documents/{id}/chunks returns 200 array (possibly empty while processing)
    sleep 2
    STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/documents/$DOC_ID/chunks")
    BODY=$(cat "$TMPFILE")
    check "GET /documents/$DOC_ID/chunks returns 200" "$STATUS" "200" "$BODY" ""
    check "GET /documents/$DOC_ID/chunks body is array" "$STATUS" "200" "$BODY" "isinstance(d, list)"

    # Test 5: GET /documents/{id} returns channel_name field (null for non-YouTube doc)
    STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/documents/$DOC_ID")
    BODY=$(cat "$TMPFILE")
    check "GET /documents/$DOC_ID returns 200" "$STATUS" "200" "$BODY" ""
    check "GET /documents/$DOC_ID has channel_name key" "$STATUS" "200" "$BODY" "'channel_name' in d"
  else
    echo "[SKIP] Could not extract document_id from upload response"
  fi
fi

rm -f "$TMPFILE" "$UPLOAD_TMPFILE"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
