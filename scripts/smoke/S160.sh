#!/usr/bin/env bash
set -euo pipefail

BASE="http://localhost:7820"

# Fetch the document list to get a real document_id
DOC_ID=$(curl -s "$BASE/documents?sort=newest&page=1&page_size=1" \
  | python3 -c "import sys,json; items=json.load(sys.stdin).get('items',[]); print(items[0]['id'] if items else '')")

if [ -z "$DOC_ID" ]; then
  echo "SKIP: no documents in the library"
  exit 0
fi

# GET /flashcards/health/{document_id}
RESP=$(curl -sf "$BASE/flashcards/health/$DOC_ID")
echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'orphaned' in d, 'missing orphaned field'
assert 'mastered' in d, 'missing mastered field'
assert 'stale' in d, 'missing stale field'
assert 'uncovered_sections' in d, 'missing uncovered_sections field'
assert 'hotspot_sections' in d, 'missing hotspot_sections field'
print('S160 health report fields OK')
"
echo "S160 smoke: GET /flashcards/health/$DOC_ID OK"

# POST /flashcards/health/{document_id}/archive-mastered
ARCHIVE_RESP=$(curl -sf -X POST "$BASE/flashcards/health/$DOC_ID/archive-mastered")
echo "$ARCHIVE_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'archived' in d, 'missing archived field'
print('S160 archive-mastered archived=%d OK' % d['archived'])
"
echo "S160 smoke: POST /flashcards/health/$DOC_ID/archive-mastered OK"

# POST /flashcards/health/{document_id}/fill-uncovered (only if uncovered sections exist)
UNCOVERED_IDS=$(echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ids = d.get('uncovered_section_ids', [])
print(' '.join(ids[:2]))  # at most 2 to keep smoke fast
")

if [ -n "$UNCOVERED_IDS" ]; then
  # Build JSON array from space-separated IDs
  SECTION_IDS_JSON=$(python3 -c "
import json, sys
ids = '$UNCOVERED_IDS'.split()
print(json.dumps({'section_ids': ids}))
")
  FILL_RESP=$(curl -sf -X POST -H 'Content-Type: application/json' \
    -d "$SECTION_IDS_JSON" \
    -w "\n%{http_code}" \
    "$BASE/flashcards/health/$DOC_ID/fill-uncovered")
  HTTP_STATUS=$(echo "$FILL_RESP" | tail -1)
  FILL_BODY=$(echo "$FILL_RESP" | head -1)
  echo "$FILL_BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'queued' in d, 'missing queued field'
print('S160 fill-uncovered queued=%d OK' % d['queued'])
"
  [ "$HTTP_STATUS" -eq 202 ] || { echo "FAIL: expected HTTP 202, got $HTTP_STATUS"; exit 1; }
  echo "S160 smoke: POST /flashcards/health/$DOC_ID/fill-uncovered OK"
else
  echo "S160 smoke: fill-uncovered SKIP (no uncovered sections)"
fi
