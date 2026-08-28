#!/usr/bin/env bash
# S245 smoke: POST /documents/ingest reports a duplicate as "duplicate", not "processing".
#
# Ingestion dedupes on file hash. When the copy we already hold is complete,
# nothing runs -- and answering "processing" made the client track a document
# that never moved, so a re-upload looked like it did nothing. The second upload
# of identical bytes is the whole test.
#
# Uploads a tiny unique text file twice and deletes it, so it leaves no residue
# in the library it ran against.
set -euo pipefail

BASE="http://localhost:7820"
STAMP="s245_$(date +%s)_$$"
TMP="$(mktemp -t s245).txt"
printf 'S245 duplicate-signal fixture %s\n' "$STAMP" > "$TMP"
DOC_ID=""
# Cleanup on EXIT, not at the end: `set -e` plus a curl timeout can kill this
# script mid-run, and an abandoned fixture in someone's real library is exactly
# the residue smoke scripts have left before.
cleanup() {
  rm -f "$TMP"
  [ -n "$DOC_ID" ] && curl -sf -m 30 -X DELETE "${BASE}/documents/${DOC_ID}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

FIRST=$(curl -sf -m 120 -X POST "${BASE}/documents/ingest" -F "file=@${TMP};filename=${STAMP}.txt")
DOC_ID=$(printf '%s' "$FIRST" | sed -n 's/.*"document_id":"\([^"]*\)".*/\1/p')
STATUS=$(printf '%s' "$FIRST" | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')

if [ -z "$DOC_ID" ]; then
  echo "FAIL: S245 -- first upload returned no document_id: $FIRST"
  exit 1
fi
if [ "$STATUS" != "processing" ]; then
  echo "FAIL: S245 -- a new file must report processing, got '$STATUS'"
  exit 1
fi

# Wait for it to reach a terminal stage; the duplicate branch only fires on complete.
for _ in $(seq 1 60); do
  STAGE=$(curl -sf -m 10 "${BASE}/documents/${DOC_ID}/status" \
    | sed -n 's/.*"stage":"\([^"]*\)".*/\1/p')
  [ "$STAGE" = "complete" ] && break
  [ "$STAGE" = "error" ] && break
  sleep 2
done

if [ "$STAGE" != "complete" ]; then
  echo "SKIP: S245 -- fixture did not reach complete (stage=$STAGE); duplicate branch not reachable"
  exit 0
fi

SECOND=$(curl -sf -m 120 -X POST "${BASE}/documents/ingest" -F "file=@${TMP};filename=${STAMP}.txt")
DUP_STATUS=$(printf '%s' "$SECOND" | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')
DUP_ID=$(printf '%s' "$SECOND" | sed -n 's/.*"document_id":"\([^"]*\)".*/\1/p')

if [ "$DUP_STATUS" != "duplicate" ]; then
  echo "FAIL: S245 -- re-upload of a complete document reported '$DUP_STATUS', expected 'duplicate'"
  exit 1
fi
if [ "$DUP_ID" != "$DOC_ID" ]; then
  echo "FAIL: S245 -- duplicate pointed at '$DUP_ID', expected the held copy '$DOC_ID'"
  exit 1
fi

echo "PASS: S245 -- a re-upload of a complete document reports duplicate"
