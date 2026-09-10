#!/usr/bin/env bash
# Smoke test for S250: the engine offer's contract, and the claim it makes.
#
# What this guards: `EngineChoice` is mounted only by the first-run guide, which
# the Hub renders only for an empty library, so every library that already
# existed kept the `private` default without being asked. `mode_chosen` is what
# lets that library be offered the question -- it reads whether the settings row
# exists at all, because the *value* is `private` either way.
#
# Verifies:
#   1. backend is healthy
#   2. GET /settings/llm reports mode_chosen, offer_dismissed and
#      keyring_available -- a default is not a decision, and a container has no
#      keychain to promise
#   3. PATCH /settings/llm accepts offer_dismissed, so "not now" survives a restart
#   4. the settings payload carries no raw API key
#   5. in private mode the routing report names nothing leaving the machine,
#      which is what the offer says about the arm the reader is already on
#   6. work that is not routable is on-device in every mode
#
# Non-destructive: reads only. Nothing here writes a setting -- a PATCH would
# create the very row whose absence check 2 is about.
set -euo pipefail

BASE="${BASE:-http://localhost:7820}"
FAIL=0

check() {
    local desc="$1" expected="$2" actual="$3"
    if [ "$actual" != "$expected" ]; then
        echo "FAIL: $desc (expected=$expected, actual=$actual)"
        FAIL=1
    else
        echo "PASS: $desc"
    fi
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/health")
check "backend healthy" "200" "$HTTP"

check "the settings payload answers whether anyone chose" "ok" "$(curl -s "$BASE/settings/llm" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for field in ('mode_chosen', 'offer_dismissed', 'keyring_available'):
    if field not in data:
        print(f'{field} missing: the offer cannot tell a default from a decision')
        raise SystemExit
    if not isinstance(data[field], bool):
        print(f'{field} is {type(data[field]).__name__}, not a bool')
        raise SystemExit
print('ok')
")"

check "a dismissal can be recorded" "ok" "$(curl -s "$BASE/openapi.json" | python3 -c "
import sys, json
spec = json.load(sys.stdin)
props = spec['components']['schemas']['LLMSettingsPatch']['properties']
if 'offer_dismissed' not in props:
    print('PATCH /settings/llm cannot record a dismissal; the notice would return every launch')
    raise SystemExit
print('ok')
")"

check "no raw key in the settings payload" "ok" "$(curl -s "$BASE/settings/llm" | python3 -c "
import sys, json
blob = sys.stdin.read()
for marker in ('sk-ant-', 'sk-proj-', 'AIzaSy'):
    if marker in blob:
        print(f'a raw key ({marker}...) is being served by GET /settings/llm')
        raise SystemExit
json.loads(blob)
print('ok')
")"

MODE=$(curl -s "$BASE/settings/llm" | python3 -c "import sys, json; print(json.load(sys.stdin)['mode'])")
check "the routing report agrees with the mode in force" "ok" "$(curl -s "$BASE/settings/llm/routing" | MODE="$MODE" python3 -c "
import os, sys, json
report = json.load(sys.stdin)
mode = os.environ['MODE']
leaving = report['leaves_device']
if mode == 'private' and leaving:
    print(f'private mode reports {leaving} leaving the machine')
    raise SystemExit
if mode != 'private' and not leaving:
    print(f'{mode} mode reports nothing leaving; the receipt and the table disagree')
    raise SystemExit
print('ok')
")"

check "work that cannot be routed stays on this machine" "ok" "$(curl -s "$BASE/settings/llm/routing" | python3 -c "
import sys, json
report = json.load(sys.stdin)
stuck = [w['id'] for w in report['work'] if not w['routable'] and not w['on_device']]
if stuck:
    print(f'not routable and not on device: {stuck}')
    raise SystemExit
if not any(not w['routable'] for w in report['work']):
    print('no unroutable work at all -- the report has nothing to say about the floor')
    raise SystemExit
print('ok')
")"

if [ "$FAIL" -eq 0 ]; then
    echo "S250: all smoke checks passed"
else
    exit 1
fi
