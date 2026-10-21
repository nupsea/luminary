#!/usr/bin/env bash
# Smoke test for S259: an EPUB's place inside a chapter, and its bookmark
# Requires a running backend with at least one ingested document. Restores what it changes.

set -euo pipefail
source "$(dirname "$0")/lib.sh"

DOC_ID=$(curl -sf "${BASE}/documents" | python3 -c "import sys,json; docs=json.load(sys.stdin).get('items',[]); print(docs[0]['id'] if docs else '')")
if [ -z "$DOC_ID" ]; then
  echo "SKIP: no documents in DB -- ingest a document first"
  exit "$SMOKE_SKIP"
fi
URL="${BASE}/documents/${DOC_ID}"
SAVED=$(curl -s "${URL}/position")

restore() {
  curl -s -o /dev/null -X DELETE "${URL}/bookmark"
  echo "$SAVED" | python3 -c "
import sys, json, urllib.request
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
if 'document_id' not in d:
    sys.exit(0)
def send(method, path, body):
    req = urllib.request.Request('${URL}' + path, data=json.dumps(body).encode(), method=method,
                                 headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req).read()
send('POST', '/position', d)
if d.get('pdf_bookmark_page') is not None:
    send('PUT', '/bookmark', {'pdf_page': d['pdf_bookmark_page']})
elif d.get('epub_bookmark_chapter_index') is not None:
    send('PUT', '/bookmark', {'epub_chapter_index': d['epub_bookmark_chapter_index'],
                              'epub_block_index': d.get('epub_bookmark_block_index') or 0})
"
}
trap restore EXIT

curl -sf -X POST -H "Content-Type: application/json" \
  -d '{"last_epub_chapter_index":4,"last_epub_block_index":120}' "${URL}/position" >/dev/null
curl -sf -X PUT -H "Content-Type: application/json" \
  -d '{"epub_chapter_index":2,"epub_block_index":17}' "${URL}/bookmark" >/dev/null
curl -sf "${URL}/position" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert (d['last_epub_chapter_index'], d['last_epub_block_index']) == (4, 120), d
assert (d['epub_bookmark_chapter_index'], d['epub_bookmark_block_index']) == (2, 17), d
"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X PUT -H "Content-Type: application/json" \
  -d '{"pdf_page":3,"epub_chapter_index":1}' "${URL}/bookmark")
if [ "$STATUS" != "422" ]; then
  echo "FAIL: a bookmark naming both a page and a chapter returned ${STATUS}, expected 422"
  exit 1
fi

echo "PASS: S259 smoke test passed"
