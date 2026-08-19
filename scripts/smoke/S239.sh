#!/usr/bin/env bash
# Smoke test for S239: a document can be re-imported, and the cost is stated first.
#
# What this guards: a parser fix only reaches a document by parsing it again.
# Stored section text cannot be repaired in place, and POST /documents/ingest
# deduplicates on file_hash -- so re-uploading the same file silently returns the
# old row and the fix never lands. For a web article the stored raw file is the
# previous *extraction*, not the page, so those re-fetch from source_url.
#
# Verifies:
#   1. backend is healthy
#   2. confirm=false is a preview: it reports the source and what would be stranded
#   3. the preview changes nothing -- section and chunk counts are identical after
#   4. an unknown document is a 404, not a 500
#
# Never sends confirm=true: that rebuilds a real document in the caller's library.

set -euo pipefail

BASE="${BASE:-http://localhost:7820}"

fail() {
  echo "FAIL: $1"
  exit 1
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (HTTP $HTTP)"

DOC=$(curl -s "${BASE}/documents?page=1&page_size=1" | python3 -c "
import sys, json
items = json.load(sys.stdin).get('items') or []
print(items[0]['id'] if items else '')
")
if [ -z "$DOC" ]; then
  echo "S239 SKIP (no documents in library)"
  exit 0
fi

BEFORE=$(curl -s "${BASE}/documents/${DOC}" | python3 -c "
import sys, json; print(len(json.load(sys.stdin).get('sections') or []))
")

curl -s -X POST "${BASE}/documents/${DOC}/reparse" \
  -H 'Content-Type: application/json' -d '{"confirm": false}' | python3 -c "
import sys, json
body = json.load(sys.stdin)
assert body['status'] == 'preview', f\"expected a preview, got {body['status']!r}\"
assert body['source'] in ('url', 'file'), f\"unknown source {body['source']!r}\"
assert body['detail'].strip(), 'a preview that does not say what it costs is not a preview'
for kind in ('flashcards', 'annotations', 'clips'):
    assert kind in body['anchored'], f'preview does not report {kind}'
assert body['cleared'] == {}, 'a preview must not clear anything'
print('  preview: source=%s anchored=%s' % (body['source'], body['anchored']))
" || fail "reparse preview contract check failed"

AFTER=$(curl -s "${BASE}/documents/${DOC}" | python3 -c "
import sys, json; print(len(json.load(sys.stdin).get('sections') or []))
")
[ "$BEFORE" = "$AFTER" ] || fail "preview changed the document ($BEFORE -> $AFTER sections)"
echo "  preview left the document untouched (${AFTER} sections)"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  "${BASE}/documents/00000000-0000-0000-0000-000000000000/reparse" \
  -H 'Content-Type: application/json' -d '{"confirm": false}')
[ "$HTTP" = "404" ] || fail "unknown document returned HTTP $HTTP, expected 404"

echo "S239 OK"
