#!/usr/bin/env bash
# Smoke test for S241: the library's filters are offered from counts, not guessed.
#
# What this guards: the filter bar carried ten chips, five of which could not
# match a document in any library. `code` is not in the ContentType union at
# all, so no row can ever hold it; `epub` is a format, and an EPUB is stored
# with content_type `book`; `kindle_clippings` needs a filename check nobody
# hits; `notes` names a separate entity entirely. A client cannot tell a filter
# that matches nothing from a page that happens to hold nothing, so the counts
# have to come from the server, over the whole library.
#
# Verifies:
#   1. backend is healthy
#   2. GET /documents/facets answers with content_type and format counts
#   3. `facets` is not swallowed by /documents/{document_id}
#   4. every counted type is positive -- an absent key, never a zero
#   5. the counts agree with what filtering by that type actually returns

set -euo pipefail

BASE="${BASE:-http://localhost:7820}"

fail() {
  echo "FAIL: $1"
  exit 1
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (HTTP $HTTP)"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/documents/facets")
[ "$HTTP" = "200" ] || fail "/documents/facets returned HTTP $HTTP (route order? it must precede /{document_id})"

FACETS=$(curl -s "${BASE}/documents/facets")

echo "$FACETS" | python3 -c "
import sys, json
body = json.load(sys.stdin)
for key in ('content_types', 'formats', 'total'):
    assert key in body, f'/documents/facets has no {key}'
assert isinstance(body['content_types'], dict), 'content_types is not a mapping'
assert isinstance(body['formats'], dict), 'formats is not a mapping'

for name, n in body['content_types'].items():
    assert isinstance(n, int) and n > 0, f'{name} counted {n!r}: a zero belongs absent, not reported'
for name, n in body['formats'].items():
    assert isinstance(n, int) and n > 0, f'format {name} counted {n!r}'

assert body['total'] == sum(body['content_types'].values()), 'total disagrees with its own parts'
print('  types: %s' % ', '.join('%s=%d' % kv for kv in sorted(body['content_types'].items())))
print('  formats: %s' % ', '.join('%s=%d' % kv for kv in sorted(body['formats'].items())))
" || fail "/documents/facets contract check failed"

# A count is a claim about what filtering will return. Check one against the list.
TYPE=$(echo "$FACETS" | python3 -c "
import sys, json
types = json.load(sys.stdin)['content_types']
print(sorted(types, key=lambda k: -types[k])[0] if types else '')
")

if [ -n "$TYPE" ]; then
  CLAIMED=$(echo "$FACETS" | python3 -c "import sys, json; print(json.load(sys.stdin)['content_types']['$TYPE'])")
  ACTUAL=$(curl -s "${BASE}/documents?page_size=1&content_type=${TYPE}" | python3 -c "import sys, json; print(json.load(sys.stdin)['total'])")
  [ "$CLAIMED" = "$ACTUAL" ] || fail "facets claims ${CLAIMED} ${TYPE} documents, filtering returns ${ACTUAL}"
  echo "  ${TYPE}: facet count ${CLAIMED} matches the filtered list"
fi

echo "S241 OK"
