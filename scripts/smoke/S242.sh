#!/usr/bin/env bash
# Smoke test for S242: the reader's content call is bounded, and says what it left.
#
# What this guards: `GET /sections/{id}/content` returned every section's full
# body in one response. Measured on a 2.9M-word manual: 20.2 MB over 1,017
# sections, one of which holds 5,063,040 characters on its own -- enough for a
# browser to report the page as unresponsive, which is how it was found. The
# bound is on the call, not on the text: a shortened body carries the length of
# the whole section and stays reachable in full at its own route.
#
# Verifies:
#   1. backend is healthy
#   2. the windowed call answers with an envelope carrying total/offset/limit
#   3. the window is honoured and `total` counts the document, not the window
#   4. an over-long window is refused rather than silently served
#   5. a shortened body reports the whole section's length, and the whole
#      section is retrievable at content/{section_id}
#   6. `content` is not swallowed by the document-id route

set -euo pipefail

BASE="${BASE:-http://localhost:7820}"

fail() {
  echo "FAIL: $1"
  exit 1
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (HTTP $HTTP)"

DOC=$(curl -s "${BASE}/documents?page_size=100" | python3 -c "
import json, sys
items = json.load(sys.stdin)['items']
# The document with the most words exercises the bound; any document proves the shape.
best = max(items, key=lambda d: d.get('word_count') or 0, default=None)
print(best['id'] if best else '')
")
[ -n "$DOC" ] || { echo "S242 SKIP -- no documents in this library"; exit 0; }

PAGE=$(curl -s "${BASE}/sections/${DOC}/content?offset=0&limit=5")

echo "$PAGE" | python3 -c "
import sys, json
body = json.load(sys.stdin)
for key in ('items', 'total', 'offset', 'limit'):
    assert key in body, f'content page has no {key}'
assert isinstance(body['items'], list), 'items is not a list'
assert len(body['items']) <= 5, f\"asked for 5 sections, got {len(body['items'])}\"
assert body['limit'] == 5 and body['offset'] == 0, 'window not echoed back'
assert body['total'] >= len(body['items']), 'total counts the window, not the document'
for item in body['items']:
    assert 'content_chars' in item and 'truncated' in item, 'item cannot say whether it is whole'
    if item['truncated']:
        assert len(item['content']) < item['content_chars'], 'marked truncated but nothing was cut'
    else:
        assert len(item['content']) == item['content_chars'], 'length disagrees with the text served'
print('  window: %d of %d sections' % (len(body['items']), body['total']))
" || fail "windowed content contract check failed"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/sections/${DOC}/content?limit=5000")
[ "$HTTP" = "422" ] || fail "an oversized window returned HTTP $HTTP, expected 422"

# A shortened section must stay reachable in full. Find one if this library has one.
SECTION=$(curl -s "${BASE}/sections/${DOC}/content?offset=0&limit=200" | python3 -c "
import sys, json
items = json.load(sys.stdin)['items']
cut = [i for i in items if i['truncated']]
print(cut[0]['section_id'] if cut else (items[0]['section_id'] if items else ''))
")

if [ -n "$SECTION" ]; then
  curl -s "${BASE}/sections/${DOC}/content/${SECTION}" | python3 -c "
import sys, json
item = json.load(sys.stdin)
assert item['truncated'] is False, 'the whole-section route served a shortened section'
assert len(item['content']) == item['content_chars'], 'whole section disagrees with its own length'
print('  whole section: %s chars' % format(item['content_chars'], ','))
" || fail "whole-section route did not return the section entire"
fi

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/sections/${DOC}/content/does-not-exist")
[ "$HTTP" = "404" ] || fail "an unknown section returned HTTP $HTTP, expected 404"

echo "S242 OK"
