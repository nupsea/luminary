#!/usr/bin/env bash
# S258 smoke: deleting a document keeps its notes unless delete_notes=true.
#
# A note is the user's own writing; deleting the book it was written against
# must not take it. The default detaches the note, and delete_notes=true is the
# explicit opt-in to remove it with the document.
#
# Ingests two small fixtures, attaches a note to each, deletes one each way, and
# removes everything it created.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

KEEP_DOC="" DROP_DOC="" KEEP_NOTE="" DROP_NOTE=""
cleanup() {
  for d in "$KEEP_DOC" "$DROP_DOC"; do
    [ -n "$d" ] && curl -s -o /dev/null -m 30 -X DELETE "${BASE}/documents/${d}?delete_notes=true" || true
  done
  for n in "$KEEP_NOTE" "$DROP_NOTE"; do
    [ -n "$n" ] && curl -s -o /dev/null -m 30 -X DELETE "${BASE}/notes/${n}" || true
  done
}
trap cleanup EXIT

note_on() {
  curl -sf -m 30 -X POST "${BASE}/notes" -H 'Content-Type: application/json' \
    -d "{\"document_id\":\"$1\",\"content\":\"S258 note $$\",\"tags\":[]}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'
}

KEEP_DOC="$(smoke_ingest_fixture)"
DROP_DOC="$(smoke_ingest_fixture)"
KEEP_NOTE="$(note_on "$KEEP_DOC")"
DROP_NOTE="$(note_on "$DROP_DOC")"

code=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "${BASE}/documents/${KEEP_DOC}")
[ "$code" = "204" ] || { echo "FAIL: S258 -- default delete returned $code"; exit 1; }
KEEP_DOC=""
kept=$(curl -sf -m 30 "${BASE}/notes/${KEEP_NOTE}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["document_id"])')
[ "$kept" = "None" ] || { echo "FAIL: S258 -- kept note still points at $kept"; exit 1; }

code=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "${BASE}/documents/${DROP_DOC}?delete_notes=true")
[ "$code" = "204" ] || { echo "FAIL: S258 -- delete_notes=true returned $code"; exit 1; }
DROP_DOC=""
code=$(curl -s -o /dev/null -w '%{http_code}' "${BASE}/notes/${DROP_NOTE}")
[ "$code" = "404" ] || { echo "FAIL: S258 -- note survived delete_notes=true ($code)"; exit 1; }
DROP_NOTE=""

echo "PASS: S258 -- document delete keeps notes by default, removes them on request"
