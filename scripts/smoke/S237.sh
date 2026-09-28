#!/usr/bin/env bash
# Smoke test for S237: a card reports whether its answer was checked, and the
# checker is never the model that wrote it.
#
# What this guards: `grounding` proves a card quotes text that exists. It cannot
# prove the answer says what that text says -- a model can quote a real sentence
# and then write what it already believed. That second question needs a model,
# which makes WHICH model load-bearing: measured on 59 live cards, phi4-mini
# called 54 supported and granite3.2:8b called 53, agreeing with a 14B on the
# pass/fail call 0.41 and 0.42 of the time. So there is no small-model default,
# and an unconfigured checker leaves cards `unchecked` rather than passed.
#
# Verifies:
#   1. backend is healthy
#   2. FlashcardResponse carries `factuality` separately from `grounding`
#   3. the two are distinct fields -- collapsing them would let a real quote
#      certify an unsupported answer
#
# That the checker is never the generation model is test_flashcard_factuality.py's.
#
# Generates no cards: one generation with the checker on costs a model switch
# plus a call per card.

set -euo pipefail
source "$(dirname "$0")/lib.sh"

fail() {
  echo "FAIL: $1"
  exit 1
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (HTTP $HTTP)"

smoke_openapi | python3 -c "
import sys, json
props = json.load(sys.stdin)['components']['schemas']['FlashcardResponse']['properties']
for name in ('grounding', 'factuality'):
    assert name in props, f'a card cannot report {name}'
print('  a card reports grounding and factuality separately')
" || fail "factuality is not on the wire"

echo "PASS: S237 -- card factuality is reported separately from grounding"
