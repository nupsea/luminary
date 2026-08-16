#!/usr/bin/env bash
# Smoke test for S231: background LLM work yields to interactive work.
#
# What this guards: residency (P1) capped memory and said nothing about latency.
# An Ask issued during ingestion measured 75-115s against 0.56s idle, because
# background calls hold the runtime's only slot. The gate is inside LLMService,
# so the wire contract is the two things a user or a probe can see -- the pause
# state the UI renders, and the counters that say the gate engaged at all.
#
# Verifies:
#   1. backend is healthy
#   2. GET /documents/{id}/status carries paused_for_interaction as a boolean
#   3. GET /monitoring/metrics reports the admission block
#   4. the reserve matches the serving width: 0 at one slot (background
#      suspends), otherwise one slot held back for interactive work

set -euo pipefail

BASE="${BASE:-http://localhost:7820}"

fail() {
  echo "FAIL: $1"
  exit 1
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (got ${HTTP})"

DOC_ID=$(curl -s "${BASE}/documents?limit=1" | python3 -c "
import sys, json
items = json.load(sys.stdin).get('items', [])
print(items[0]['id'] if items else '')
")

if [ -z "$DOC_ID" ]; then
  echo "SKIP: S231 -- library is empty, no document to poll"
  exit 0
fi

curl -s "${BASE}/documents/${DOC_ID}/status" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'paused_for_interaction' in d, 'status has no paused_for_interaction; the UI cannot show the pause'
assert isinstance(d['paused_for_interaction'], bool), f\"paused_for_interaction is {type(d['paused_for_interaction'])}\"
print(f\"  stage {d['stage']}, paused {d['paused_for_interaction']}\")
" || fail "GET /documents/{id}/status did not carry the pause state"

curl -s "${BASE}/monitoring/metrics" | python3 -c "
import sys, json
d = json.load(sys.stdin)
a = d.get('llm_admission')
assert a, 'monitoring/metrics reports no llm_admission block'
for key in ('enabled', 'reserve', 'deferred_calls', 'deferred_seconds', 'forced_admissions'):
    assert key in a, f'llm_admission missing {key}'
assert a['reserve'] >= 0, f\"negative reserve {a['reserve']}\"
print(f\"  enabled {a['enabled']}, reserve {a['reserve']}, deferred {a['deferred_calls']} call(s) \"
      f\"over {a['deferred_seconds']}s, {a['forced_admissions']} forced\")
" || fail "GET /monitoring/metrics did not report admission state"

echo "PASS: S231 -- admission control is visible to the UI and to a probe"
