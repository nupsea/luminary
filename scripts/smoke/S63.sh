#!/usr/bin/env bash
# Smoke test for S63 — content type selection in upload
#
# content_type is optional: omitting it is the request to classify. It was
# mandatory until the upload dialog was found to be pre-labelling every
# non-media file, which switched detection off for everything a user uploaded.
set -euo pipefail

# BSD mktemp only substitutes Xs at the END of a template, so
# `mktemp /tmp/foo.XXXXXX.json` created that name literally: the script worked
# once per machine and then failed "File exists" forever. One per-run directory
# keeps the extensions -- uploads are validated on them -- and cleans up itself.
SMOKE_TMPDIR=$(mktemp -d)

BASE="http://localhost:7820"

# A real file this script creates. /etc/hostname was used here and does not
# exist on macOS, so curl exited 26 ("couldn't read file") and every check
# after the first failed for a reason that had nothing to do with the endpoint.
FIXTURE="$SMOKE_TMPDIR/s63fixture.txt"
echo "S63 smoke fixture." > "$FIXTURE"
trap 'rm -f "$FIXTURE"; rm -rf "$SMOKE_TMPDIR"' EXIT

echo "[S63] Test 1: POST /documents/ingest without content_type is accepted"
TMP1="$SMOKE_TMPDIR/s63auto.txt"
echo "A short note written for the S63 smoke test." > "$TMP1"
RESP1=$(curl -s -X POST "${BASE}/documents/ingest" -F "file=@${TMP1};filename=s63_auto.txt")
rm -f "$TMP1"
echo "$RESP1" | grep -q "document_id" || { echo "FAIL: expected document_id, got: $RESP1"; exit 1; }
AUTO_ID=$(echo "$RESP1" | python3 -c "import sys,json; print(json.load(sys.stdin)['document_id'])")
curl -s -o /dev/null -X DELETE "${BASE}/documents/${AUTO_ID}"
echo "PASS: omitted content_type accepted (classification runs)"

echo "[S63] Test 2: POST /documents/ingest with invalid content_type returns 422"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/documents/ingest" \
  -F "file=@${FIXTURE}" \
  -F "content_type=invalid_type")
if [ "$STATUS" != "422" ]; then
  echo "FAIL: expected 422, got $STATUS"
  exit 1
fi
echo "PASS: 422 returned for invalid content_type"

echo "[S63] Test 3: POST /documents/ingest with valid content_type returns 200"
TMP="$SMOKE_TMPDIR/s63test.txt"
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

# The script creates a document in Test 3; leaving one behind per run
# accumulates in whatever library the smoke suite is pointed at.
curl -s -o /dev/null -X DELETE "${BASE}/documents/${DOC_ID}"

echo "[S63] All smoke tests passed."
