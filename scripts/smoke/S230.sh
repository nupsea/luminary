#!/usr/bin/env bash
# Smoke test for S230: model choice resolves in one place.
#
# The defect this guards: flashcard generation read LITELLM_GENERATION_MODEL
# straight from config, so a model chosen in Settings applied to chat and
# silently did not apply to the cards. Both paths returned a model, so nothing
# failed -- the two answers just disagreed.
#
# Verifies:
#   1. backend is healthy
#   2. every role resolves to a non-empty model
#   3. with no generation override configured, generation == chat, which is the
#      assertion that fails if generation goes back to reading config
#   4. vision resolves through the same router, reported beside the text roles

set -euo pipefail

BASE="http://localhost:7820"

fail() {
  echo "FAIL: $1"
  exit 1
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (got ${HTTP})"

BODY=$(curl -s -w "\n%{http_code}" "${BASE}/evals/environment")
HTTP=$(echo "$BODY" | tail -1)
[ "$HTTP" = "200" ] || fail "GET /evals/environment expected 200, got ${HTTP}"

echo "$BODY" | head -1 | python3 -c "
import sys, json
d = json.load(sys.stdin)

for role in ('chat_model', 'generation_model', 'background_model', 'vision_model'):
    assert d.get(role), f'{role} resolved to nothing'

# No override is configured in this environment, so generation follows the model
# a user chose. If this fails, generation is reading config again.
assert d['generation_model'] == d['chat_model'], (
    f\"generation {d['generation_model']} does not follow chat {d['chat_model']}; \"
    'a Settings change would not reach flashcard generation'
)

print(f\"  chat/generation {d['chat_model']}\")
print(f\"  vision          {d['vision_model']}\")
" || fail "model roles did not resolve consistently"

echo "PASS: S230 -- model roles resolve through one router"
