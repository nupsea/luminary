#!/usr/bin/env bash
# Smoke test for S233: comparing models from the app.
#
# What this guards: a comparison owns the model selection for its whole duration
# and some stages write generated content into the library. Every refusal below
# exists because the alternative is a number that cannot be defended, or a
# backend left serving a model the user did not choose.
#
# Verifies:
#   1. backend is healthy
#   2. GET /model-lab/catalogue lists the workflow stages, the goldens and the
#      models, and says which stages write to the library
#   3. a model id that a child runner's argparse could re-parse as a flag is
#      refused (422), not spread into argv
#   4. an unknown stage and an unknown golden are refused (422)
#   5. an unknown run id is a 404 rather than an empty 200
#
# Deliberately does NOT start a run: one takes minutes to hours and would change
# the selected model on a live machine.

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

curl -s "${BASE}/model-lab/catalogue" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for key in ('tasks', 'qa_datasets', 'installed_models', 'current_model', 'busy'):
    assert key in d, f'catalogue missing {key}'

keys = {t['key'] for t in d['tasks']}
assert {'intent', 'flashcards', 'summary'} <= keys, f'stages missing: {sorted(keys)}'
for t in d['tasks']:
    assert isinstance(t['mutates_library'], bool), t['key']
    assert t['typical_seconds'] > 0, t['key']

# A stage that writes generated content into the library must say so, or the
# confirmation the UI shows is a generic warning nobody reads.
writers = {t['key'] for t in d['tasks'] if t['mutates_library']}
assert 'flashcards' in writers, 'flashcards does not declare that it writes to the library'

assert d['qa_datasets'], 'no goldens found for the answering stage'
print(f\"  {len(d['tasks'])} stage(s), {len(d['qa_datasets'])} golden(s), \"
      f\"{len(d['installed_models'])} model(s) installed\")
print(f\"  current model {d['current_model']}, busy={d['busy']}\")
" || fail "GET /model-lab/catalogue did not describe the lab"

# An argv-injectable model id. A single-value option consumes one token, but a
# value that can start with '-' is re-parsed by the child's argparse as a flag.
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/model-lab/runs" \
  -H 'Content-Type: application/json' \
  -d '{"models":["--out"],"tasks":["intent"]}')
expect_status "argv-injectable model id refused" 422 "$HTTP"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/model-lab/runs" \
  -H 'Content-Type: application/json' \
  -d '{"models":["ollama/llama3.2"],"tasks":["not-a-stage"]}')
expect_status "unknown stage refused" 422 "$HTTP"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/model-lab/runs" \
  -H 'Content-Type: application/json' \
  -d '{"models":["ollama/llama3.2"],"tasks":["intent"],"qa_datasets":["no-such-golden"]}')
expect_status "unknown golden refused" 422 "$HTTP"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/model-lab/runs/does-not-exist")
expect_status "unknown run id is 404" 404 "$HTTP"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/model-lab/runs")
expect_status "run list reachable" 200 "$HTTP"

echo "PASS: S233 -- the model lab is reachable and refuses what it should"
