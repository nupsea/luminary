#!/usr/bin/env bash
# Smoke test for S236: the flashcard search index agrees with the flashcards.
#
# What this guards: three paths left the index and the card table disagreeing, and
# no user action could clear it. A real library carried 228 index rows naming a
# deleted card, 71 child rows naming one, and 1 card never indexed at all -- which
# meant flashcard search returned cards that no longer existed and could not return
# one that did.
#
# Verifies:
#   1. backend is healthy
#   2. POST /flashcards/repair runs and reports all three counts
#   3. after it, the index and the card table agree -- a second run is all zeroes
#   4. repair deletes no flashcards
#
# Deletes nothing a user would miss: repair only drops rows naming a card that is
# already gone, and never touches review_events.

set -euo pipefail

BASE="${BASE:-http://localhost:7820}"

fail() {
  echo "FAIL: $1"
  exit 1
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (HTTP $HTTP)"

BEFORE=$(curl -s "${BASE}/flashcards/grounding" | python3 -c "import sys,json; print(json.load(sys.stdin)['scanned'])")

curl -s -X POST "${BASE}/flashcards/repair" | python3 -c "
import sys, json
r = json.load(sys.stdin)
for key in ('index_rows_removed', 'cards_indexed', 'orphan_rows_removed'):
    assert key in r, f'repair does not report {key}'
print('  repaired: ' + ', '.join(f'{k} {v}' for k, v in r.items()))
" || fail "repair did not run"

curl -s -X POST "${BASE}/flashcards/repair" | python3 -c "
import sys, json
r = json.load(sys.stdin)
assert not any(r.values()), f'a second repair still had work to do: {r}'
print('  a second repair changes nothing')
" || fail "repair is not idempotent"

AFTER=$(curl -s "${BASE}/flashcards/grounding" | python3 -c "import sys,json; print(json.load(sys.stdin)['scanned'])")
[ "$BEFORE" = "$AFTER" ] || fail "repair changed the card count ($BEFORE -> $AFTER); it must delete no flashcards"

echo "PASS: S236 -- the flashcard search index agrees with the flashcards"
