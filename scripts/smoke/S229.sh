#!/usr/bin/env bash
# Smoke test for S229: GET /evals/output-stats -- what model output needed to be usable.
#
# Verifies:
#   1. backend is healthy
#   2. GET /evals/output-stats -- 200, with counts and both rates present
#   3. counters are monotonic: a second read is never lower than the first
#   4. rates are null rather than 0.0 before anything has parsed, because a
#      first-pass rate of 0.0 on zero parses reads as a model that never emits
#      clean JSON

set -euo pipefail

BASE="http://localhost:7820"

fail() {
  echo "FAIL: $1"
  exit 1
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (got ${HTTP})"

FIRST=$(curl -s -w "\n%{http_code}" "${BASE}/evals/output-stats")
HTTP=$(echo "$FIRST" | tail -1)
[ "$HTTP" = "200" ] || fail "GET /evals/output-stats expected 200, got ${HTTP}"
BODY_ONE=$(echo "$FIRST" | head -1)

echo "$BODY_ONE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for key in ('counts', 'first_pass_rate', 'attempts_per_generation'):
    assert key in d, f'missing {key}'
assert isinstance(d['counts'], dict), 'counts is not an object'
for name, value in d['counts'].items():
    assert isinstance(value, int), f'{name} is not an integer'
rate = d['first_pass_rate']
if not d['counts'].get('parses'):
    assert rate is None, f'no parses yet but first_pass_rate is {rate}'
else:
    assert 0.0 <= rate <= 1.0, f'first_pass_rate out of range: {rate}'
print(f\"  parses={d['counts'].get('parses', 0)}  first_pass_rate={rate}\")
" || fail "GET /evals/output-stats did not return usable counters"

BODY_TWO=$(curl -s "${BASE}/evals/output-stats")
python3 -c "
import json, sys
one = json.loads(sys.argv[1])['counts']
two = json.loads(sys.argv[2])['counts']
lower = [k for k, v in one.items() if two.get(k, 0) < v]
assert not lower, f'counters went down: {lower}'
" "$BODY_ONE" "$BODY_TWO" || fail "counters are not monotonic"

echo "PASS: S229 -- /evals/output-stats reports monotonic repair counters"
