#!/usr/bin/env bash
# Smoke test for S192 -- DocumentReader notes panel: auto-collection endpoints
set -euo pipefail

BASE="http://localhost:7820"
FAIL=0

echo "=== S192 Smoke: Auto-collection endpoints ==="

# Step 1: GET /collections/by-document with nonexistent doc -> 404
echo "[1/5] GET /collections/by-document/{fake_id} -> 404"
TMPFILE=$(mktemp /tmp/s192_1_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/collections/by-document/smoke-nonexistent-doc")
rm -f "$TMPFILE"
if [ "$STATUS" = "404" ]; then
  echo "  PASS: 404 for missing auto-collection"
else
  echo "  FAIL: expected 404, got $STATUS"
  FAIL=1
fi

# Step 2: POST /collections/auto with nonexistent doc -> 404
echo "[2/5] POST /collections/auto/{fake_id} -> 404"
TMPFILE=$(mktemp /tmp/s192_2_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X POST "$BASE/collections/auto/smoke-nonexistent-doc")
rm -f "$TMPFILE"
if [ "$STATUS" = "404" ]; then
  echo "  PASS: 404 for missing document"
else
  echo "  FAIL: expected 404, got $STATUS"
  FAIL=1
fi

# Step 3: Find an existing document to test with
echo "[3/5] Finding an existing document..."
TMPFILE=$(mktemp /tmp/s192_3_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/documents?limit=1")
BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"
if [ "$STATUS" != "200" ]; then
  echo "  SKIP: no documents endpoint or no documents available ($STATUS)"
  echo "  Testing with 404 paths only"
else
  DOC_ID=$(echo "$BODY" | python3 -c "import sys,json; docs=json.load(sys.stdin); print(docs[0]['id'] if docs else '')" 2>/dev/null || true)
  if [ -n "$DOC_ID" ]; then
    echo "  Found document: $DOC_ID"

    # Step 4: POST /collections/auto/{doc_id} -> 201
    echo "[4/5] POST /collections/auto/{doc_id} -> 201"
    TMPFILE=$(mktemp /tmp/s192_4_XXXXXX.json)
    STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X POST "$BASE/collections/auto/$DOC_ID")
    BODY=$(cat "$TMPFILE")
    rm -f "$TMPFILE"
    if [ "$STATUS" = "201" ]; then
      echo "  PASS: auto-collection created"
      # Verify auto_document_id field
      ADI=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('auto_document_id',''))" 2>/dev/null || true)
      if [ "$ADI" = "$DOC_ID" ]; then
        echo "  PASS: auto_document_id matches"
      else
        echo "  FAIL: auto_document_id mismatch: $ADI != $DOC_ID"
        FAIL=1
      fi
    else
      echo "  FAIL: expected 201, got $STATUS"
      FAIL=1
    fi

    # Step 5: GET /collections/by-document/{doc_id} -> 200
    echo "[5/5] GET /collections/by-document/{doc_id} -> 200"
    TMPFILE=$(mktemp /tmp/s192_5_XXXXXX.json)
    STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/collections/by-document/$DOC_ID")
    rm -f "$TMPFILE"
    if [ "$STATUS" = "200" ]; then
      echo "  PASS: auto-collection retrieved"
    else
      echo "  FAIL: expected 200, got $STATUS"
      FAIL=1
    fi
  else
    echo "  SKIP: no documents in library"
  fi
fi

if [ "$FAIL" -ne 0 ]; then
  echo "=== S192 SMOKE FAILED ==="
  exit 1
fi

echo "=== S192 SMOKE PASSED ==="
exit 0
