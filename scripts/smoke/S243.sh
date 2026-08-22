#!/usr/bin/env bash
# Smoke test for S243: "Regenerate (replace)" is one request per source, and a
# run that produces nothing leaves that source's deck alone.
#
# What this guards: the UI used to delete the deck and then generate. Two
# consequences shipped. The near-duplicate filter compares a new card against
# the cards the document already has, so wiping them first left it comparing
# against an empty deck and the replacement could return exactly what had just
# been removed. And when the quality gate dropped cards the backfill could not
# replace, the deck silently shrank -- 5 asked for, 3 delivered, announced as a
# clean replacement.
#
# Verifies:
#   1. backend is healthy
#   2. POST /flashcards/regenerate exists and answers 201
#   3. the response reports requested/delivered/replaced separately, so a short
#      delivery cannot be announced as a full one
#   4. a document with nothing to generate from returns kept_previous=true and
#      deletes nothing
#   5. /flashcards/generate no longer takes `avoid` -- listing the previous
#      questions verbatim in the prompt is the I-28 anti-pattern this replaced
#   6. a note is a source too, and exactly one source is accepted per call --
#      a collection replaces its sources one at a time so a failed run costs
#      one source's cards, not the collection's
#
# Costs no model time: an unknown document has no chunks, so generation returns
# before any LLM call.

set -euo pipefail

BASE="${BASE:-http://localhost:7820}"

fail() {
  echo "FAIL: $1"
  exit 1
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (HTTP $HTTP)"

curl -s "${BASE}/openapi.json" | python3 -c "
import sys, json
schemas = json.load(sys.stdin)['components']['schemas']
report = schemas['RegenerateResponse']['properties']
for field in ('cards', 'requested', 'delivered', 'replaced', 'kept_previous'):
    assert field in report, f'a replacement cannot report {field}'
request = schemas['FlashcardRegenerateRequest']['properties']
for field in ('document_id', 'note_id'):
    assert field in request, f'a {field} cannot be replaced'
assert 'avoid' not in schemas['FlashcardGenerateRequest']['properties'], (
    'the previous questions are back in the prompt; see I-28'
)
print('  the replacement takes either source and reports three counts')
" || fail "regenerate request/response shape is wrong"

BODY=$(curl -s -w '\n%{http_code}' -X POST "${BASE}/flashcards/regenerate" \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"s243-no-such-document","count":5}')
CODE=$(echo "$BODY" | tail -n1)
JSON=$(echo "$BODY" | sed '$d')
[ "$CODE" = "201" ] || fail "regenerate returned HTTP $CODE"

echo "$JSON" | python3 -c "
import sys, json
r = json.load(sys.stdin)
assert r['kept_previous'] is True, 'a run that produced nothing must say so'
assert r['delivered'] == 0, f\"delivered {r['delivered']} cards from no document\"
assert r['replaced'] == 0, 'nothing may be deleted when nothing was generated'
assert r['cards'] == [], 'no cards can come from a document that does not exist'
print('  nothing generated -> nothing deleted, reported as kept_previous')
" || fail "an empty run did not leave the deck alone"

# count is bounded: the UI sends the deck's own size, and 0 means "keep it".
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/flashcards/regenerate" \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"s243-no-such-document","count":500}')
[ "$HTTP" = "422" ] || fail "an out-of-range count was accepted (HTTP $HTTP)"

# A note is a source in its own right: a collection's note cards were previously
# unreachable, so a collection replace stacked new note cards on top of the old.
BODY=$(curl -s -w '\n%{http_code}' -X POST "${BASE}/flashcards/regenerate" \
  -H 'Content-Type: application/json' \
  -d '{"note_id":"s243-no-such-note","count":3}')
CODE=$(echo "$BODY" | tail -n1)
[ "$CODE" = "201" ] || fail "a note source returned HTTP $CODE"
echo "$BODY" | sed '$d' | python3 -c "
import sys, json
r = json.load(sys.stdin)
assert r['kept_previous'] is True and r['replaced'] == 0, 'an empty note run deleted something'
print('  a note is a source, and an empty run deletes none of its cards')
" || fail "the note source does not behave like the document source"

# Exactly one source per call: two, or none, is a 422 rather than a guess.
for BAD in '{"count":3}' '{"document_id":"a","note_id":"b","count":3}'; do
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/flashcards/regenerate" \
    -H 'Content-Type: application/json' -d "$BAD")
  [ "$HTTP" = "422" ] || fail "ambiguous source accepted: $BAD (HTTP $HTTP)"
done

echo "PASS: S243 -- regenerate replaces one source atomically and reports what it delivered"
