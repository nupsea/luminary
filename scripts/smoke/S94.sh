#!/usr/bin/env bash
# Smoke test for S94: Notes vs Book gap detection.
# Requires the backend to be running on localhost:8000.

set -euo pipefail

BASE="http://localhost:8000"
NOTE_ID=""

cleanup() {
  if [ -n "$NOTE_ID" ]; then
    curl -s -o /dev/null -X DELETE "${BASE}/notes/${NOTE_ID}" || true
  fi
}
trap cleanup EXIT

# 1. Create a note
CREATE_RESP=$(curl -s -X POST "${BASE}/notes" \
  -H "Content-Type: application/json" \
  -d '{"content":"Alice fell down a rabbit hole","tags":[]}')
NOTE_ID=$(echo "$CREATE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

if [ -z "$NOTE_ID" ]; then
  echo "FAIL: POST /notes did not return an id"
  exit 1
fi

# 2. POST /notes/gap-detect with empty note_ids -- expect 422
HTTP_422=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/notes/gap-detect" \
  -H "Content-Type: application/json" \
  -d '{"note_ids":[],"document_id":"fake-id"}')

if [ "$HTTP_422" != "422" ]; then
  echo "FAIL: POST /notes/gap-detect with empty note_ids returned ${HTTP_422} (expected 422)"
  exit 1
fi

# 3. POST /notes/gap-detect with nonexistent note_ids -- expect 404
HTTP_404=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/notes/gap-detect" \
  -H "Content-Type: application/json" \
  -d '{"note_ids":["nonexistent-uuid"],"document_id":"fake-id"}')

if [ "$HTTP_404" != "404" ]; then
  echo "FAIL: POST /notes/gap-detect with nonexistent note returned ${HTTP_404} (expected 404)"
  exit 1
fi

echo "PASS: S94 -- gap-detect 422 on empty note_ids, 404 on nonexistent notes"
