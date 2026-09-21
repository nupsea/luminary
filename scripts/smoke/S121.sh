#!/usr/bin/env bash
set -e
source "$(dirname "$0")/lib.sh"
# Verify the library endpoint returns expected shape
RESP=$(curl -sf "${BASE}/documents")
echo "${RESP}" | grep -q '"items"' || { echo "FAIL: /documents did not return items"; exit 1; }

# Verify video content_type filter is accepted (no 422 or 500)
FILTER_RESP=$(curl -sf "${BASE}/documents?content_type=video")
echo "${FILTER_RESP}" | grep -q '"items"' || { echo "FAIL: video filter rejected"; exit 1; }

# Verify /documents/ingest accepts .mp4 with content_type=video. The server
# validates the extension, not MIME magic, so an empty file is enough. A real
# file, not /dev/null: the mingw curl in Git Bash cannot open /dev/null.
EMPTY="$SMOKE_TMP/s121-empty.mp4"
: > "$EMPTY"
DOC_ID=""
trap '[ -n "$DOC_ID" ] && curl -s -m 30 -X DELETE "${BASE}/documents/${DOC_ID}" >/dev/null 2>&1 || true' EXIT
# No -f: a 422 is an accepted answer, and -f under set -e would end the script
# silently before the status is read.
INGEST_STATUS=$(curl -s -X POST "${BASE}/documents/ingest" \
  -F "file=@${EMPTY};filename=test.mp4;type=video/mp4" \
  -F "content_type=video" \
  -o "$SMOKE_TMP/s121-ingest.json" -w "%{http_code}")
DOC_ID=$(sed -n 's/.*"document_id":"\([^"]*\)".*/\1/p' "$SMOKE_TMP/s121-ingest.json")
# 200 = accepted, 422 = empty file rejected; both are fine for smoke.
[ "${INGEST_STATUS}" = "200" ] || [ "${INGEST_STATUS}" = "422" ] || {
  echo "FAIL: /documents/ingest returned unexpected ${INGEST_STATUS}"; exit 1;
}

echo "S121 smoke: PASS"
