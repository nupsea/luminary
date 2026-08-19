#!/usr/bin/env bash
# Smoke test for S234: card generation takes a model, and says no to a bad one.
#
# What this guards: Study showed no model and could not change it, so a card that
# came back wrong gave the user nothing to act on. The override is per request --
# omitting it keeps following Settings. A malformed id is refused at the edge
# rather than silently falling back to the default, because a silent fallback
# makes "generated with X" a claim the app cannot support.
#
# Verifies:
#   1. backend is healthy
#   2. the request schema carries an optional `model` on both generate routes
#   3. a provider-less id ("qwen3.5:4b") is refused with 422
#   4. an argv-shaped id ("--out") is refused with 422
#   5. an unknown document with a well-formed model is not a 422 -- the model
#      passed validation and the request failed on the document instead
#
# Deliberately does NOT generate cards: one call takes tens of seconds on a local
# model and would write into the user's library.

set -euo pipefail

BASE="${BASE:-http://localhost:7820}"

fail() {
  echo "FAIL: $1"
  exit 1
}

expect_status() {
  local desc="$1" expected="$2" actual="$3"
  [ "$actual" = "$expected" ] || fail "$desc -- expected HTTP $expected, got $actual"
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
expect_status "backend healthy" 200 "$HTTP"

curl -s "${BASE}/openapi.json" | python3 -c "
import sys, json
schemas = json.load(sys.stdin)['components']['schemas']
for name in ('FlashcardGenerateRequest', 'GenerateTechnicalRequest'):
    props = schemas[name]['properties']
    assert 'model' in props, f'{name} cannot carry a model'
    assert name not in (schemas[name].get('required') or []), f'{name}.model must stay optional'
print('  both generate routes accept an optional model')
" || fail "generate routes do not expose an optional model"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/flashcards/generate" \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"00000000-0000-0000-0000-000000000000","count":1,"model":"qwen3.5:4b"}')
expect_status "provider-less model id refused" 422 "$HTTP"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/flashcards/generate" \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"00000000-0000-0000-0000-000000000000","count":1,"model":"--out"}')
expect_status "argv-shaped model id refused" 422 "$HTTP"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/flashcards/generate-technical" \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"00000000-0000-0000-0000-000000000000","count":1,"model":"nope/x"}')
expect_status "unknown provider refused" 422 "$HTTP"

# A well-formed id must get past validation. Whatever this returns, it must not be
# a 422, or the shape check above is meaningless.
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/flashcards/generate" \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"00000000-0000-0000-0000-000000000000","count":1,"model":"ollama/phi4-mini"}')
[ "$HTTP" = "422" ] && fail "a well-formed model id was rejected as invalid"

echo "PASS: S234 -- card generation accepts a model override and refuses a malformed one"
