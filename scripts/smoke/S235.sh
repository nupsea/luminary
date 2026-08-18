#!/usr/bin/env bash
# Smoke test for S235: a card's grounding verdict is stored, reported, and honest.
#
# What this guards: the review screen shows `source_excerpt` under a heading that
# reads "Source". Measured on a real 949-card library, 26% of the cards that quoted
# anything quoted text their document does not contain, and nothing in the product
# could tell. `grounding` is four states rather than a boolean so that "checked and
# found" never collapses into "nothing could be checked".
#
# Verifies:
#   1. backend is healthy
#   2. GET /flashcards/grounding reports every state, `unchecked` included
#   3. the counts add up to `scanned` -- a missing state would silently vanish
#   4. FlashcardResponse carries `grounding`, so the review UI can read it
#   5. POST /flashcards/grounding/audit is idempotent: a second run changes nothing
#
# The audit is deterministic and model-free, so running it here is safe: it
# recomputes verdicts from the document's own chunks and writes no cards.

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
assert 'grounding' in schemas['FlashcardResponse']['properties'], \
    'a card cannot tell the UI whether its quote was verified'
states = schemas['GroundingReport']['properties']
for name in ('scanned', 'verified', 'unsupported', 'unverifiable', 'unchecked'):
    assert name in states, f'GroundingReport hides {name}'
print('  the card and the report both carry the verdict')
" || fail "grounding is not on the wire"

curl -s "${BASE}/flashcards/grounding" | python3 -c "
import sys, json
r = json.load(sys.stdin)
states = ('verified', 'unsupported', 'unverifiable', 'unchecked')
total = sum(r[s] for s in states)
assert total == r['scanned'], f'{total} counted vs {r[\"scanned\"]} scanned -- a state is missing'
print('  ' + ', '.join(f'{s} {r[s]}' for s in states))
" || fail "grounding summary does not add up"

curl -s -X POST "${BASE}/flashcards/grounding/audit" \
  -H 'Content-Type: application/json' -d '{}' > /tmp/s235_first.json
curl -s -X POST "${BASE}/flashcards/grounding/audit" \
  -H 'Content-Type: application/json' -d '{}' | python3 -c "
import sys, json
second = json.load(sys.stdin)
first = json.load(open('/tmp/s235_first.json'))
assert second['changed'] == 0, \
    f'a second audit changed {second[\"changed\"]} verdicts -- it is not deterministic'
for key in ('verified', 'unsupported', 'unverifiable'):
    assert first[key] == second[key], f'{key} moved between two identical audits'
print('  a second audit changes nothing')
" || fail "the audit is not idempotent"

rm -f /tmp/s235_first.json
echo "PASS: S235 -- card grounding is stored, reported by state, and stable"
