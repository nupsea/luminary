#!/usr/bin/env bash
# Smoke test for S241: the library's filters are offered from counts, not guessed.
#
# What this guards: the filter bar carried ten chips, five of which could not
# match a document in any library. A client cannot tell a filter that matches
# nothing from a page that happens to hold nothing, so the counts have to come
# from the server, over the whole library.
#
# Verifies:
#   1. backend is healthy
#   2. GET /documents/facets answers with kind and format counts
#   3. `facets` is not swallowed by /documents/{document_id}
#   4. every count is positive -- an absent key, never a zero
#   5. every kind count (#223) agrees with filtering by that kind

set -euo pipefail
source "$(dirname "$0")/lib.sh"

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
for key in ('kinds', 'formats', 'total'):
    assert key in body, f'/documents/facets has no {key}'
assert isinstance(body['formats'], dict), 'formats is not a mapping'

for name, n in [*body['kinds'].items(), *body['formats'].items()]:
    assert isinstance(n, int) and n > 0, f'{name} counted {n!r}: a zero belongs absent, not reported'

print('  formats: %s' % ', '.join('%s=%d' % kv for kv in sorted(body['formats'].items())))
" || fail "/documents/facets contract check failed"

# A count is a claim about what filtering will return. Check each against the list.
KINDS=$(echo "$FACETS" | python3 -c "
import sys, json
body = json.load(sys.stdin)
kinds = body.get('kinds')
assert isinstance(kinds, dict), '/documents/facets has no kinds mapping'
assert sum(kinds.values()) == body['total'], 'kind counts disagree with total'
print(' '.join('%s=%d' % kv for kv in sorted(kinds.items())))
") || fail "/documents/facets kinds check failed"

for PAIR in $KINDS; do
  KIND=${PAIR%%=*}
  CLAIMED=${PAIR#*=}
  ACTUAL=$(curl -s "${BASE}/documents?page_size=1&kind=${KIND}" | python3 -c "import sys, json; print(json.load(sys.stdin)['total'])")
  [ "$CLAIMED" = "$ACTUAL" ] || fail "facets claims ${CLAIMED} ${KIND} documents, filtering by kind returns ${ACTUAL}"
done
echo "  kinds: ${KINDS:-none}, each matching its filtered list"

echo "S241 OK"
