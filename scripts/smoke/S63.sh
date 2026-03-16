#!/usr/bin/env bash
# Smoke test for S63 — Mandatory content type selection in upload
set -euo pipefail

BASE="http://localhost:7820"

echo "[S63] Test 1: POST /documents/ingest without content_type returns 422"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/documents/ingest" \
  -F "file=@/etc/hostname")
if [ "$STATUS" != "422" ]; then
  echo "FAIL: expected 422, got $STATUS"
  exit 1
fi
echo "PASS: 422 returned when content_type missing"

echo "[S63] Test 2: POST /documents/ingest with invalid content_type returns 422"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/documents/ingest" \
  -F "file=@/etc/hostname" \
  -F "content_type=invalid_type")
if [ "$STATUS" != "422" ]; then
  echo "FAIL: expected 422, got $STATUS"
  exit 1
fi
echo "PASS: 422 returned for invalid content_type"

echo "[S63] Test 3: POST /documents/ingest with valid content_type returns 200"
TMP=$(mktemp /tmp/s63test.XXXXXX.txt)
echo "This is a test document for S63 smoke test." > "$TMP"
RESP=$(curl -s -X POST "${BASE}/documents/ingest" \
  -F "file=@${TMP};filename=s63_smoke.txt" \
  -F "content_type=notes")
rm -f "$TMP"
echo "$RESP" | grep -q "document_id" || { echo "FAIL: no document_id in response: $RESP"; exit 1; }
DOC_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['document_id'])")
echo "PASS: ingest returned document_id=$DOC_ID"

echo "[S63] Test 4: PATCH /documents/{id} with content_type updates the document"
PATCH_RESP=$(curl -s -X PATCH "${BASE}/documents/${DOC_ID}" \
  -H "Content-Type: application/json" \
  -d '{"content_type": "book"}')
echo "$PATCH_RESP" | grep -q '"updated":true' || { echo "FAIL: patch response missing updated=true: $PATCH_RESP"; exit 1; }
echo "$PATCH_RESP" | grep -q "Re-ingest" || { echo "FAIL: patch response missing re-ingest note: $PATCH_RESP"; exit 1; }
echo "PASS: PATCH content_type returned updated=true with re-ingest note"

echo "[S63] All smoke tests passed."
