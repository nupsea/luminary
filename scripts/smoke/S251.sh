#!/usr/bin/env bash
# Smoke test for S251: the host-support verdict, and the rule behind it.
#
# What this guards: Luminary promises a local model, and a host with no
# accelerator cannot keep that promise -- an Intel Mac through Docker decodes at
# ~6 tok/s. The native installers already refuse macOS x86_64; the container was
# the remaining door. The check is for the ACCELERATOR, never for Docker: a
# container with a GPU passed through is a first-class host, and refusing Docker
# as a class would refuse the fastest way to run Luminary and delete the shape
# the hosted version will be built in.
#
# Verifies:
#   1. backend is healthy
#   2. GET /setup/host-support answers with all four fields
#   3. a supported host carries no message and an unsupported one must
#   4. the verdict names a reason from the known set, never a free-form string
#   5. the message names both ways forward (I-16: no key still means a working app)
#
# Non-destructive: reads only.
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

check "the host verdict is complete and self-consistent" "ok" "$(curl -s "$BASE/setup/host-support" | python3 -c "
import sys, json
d = json.load(sys.stdin)
missing = [f for f in ['supported', 'reason', 'host', 'message'] if f not in d]
if missing:
    print('missing fields: %s' % missing)
    raise SystemExit
if not isinstance(d['supported'], bool):
    print('supported is not a bool')
    raise SystemExit
# A message and a supported verdict are mutually exclusive: a banner with no
# reason to show, or a refusal with nothing to say, are both defects.
if d['supported'] != (d['message'] is None):
    print('supported=%s but message=%r' % (d['supported'], d['message']))
    raise SystemExit
if d['supported'] != (d['reason'] is None):
    print('supported=%s but reason=%r' % (d['supported'], d['reason']))
    raise SystemExit
known = [None, 'intel_mac', 'container_without_accelerator', 'no_accelerator', 'under_memory_floor']
if d['reason'] not in known:
    print('unknown reason %r; a verdict nobody can act on' % d['reason'])
    raise SystemExit
if not d['host']:
    print('host is empty -- the verdict does not say what it looked at')
    raise SystemExit
if d['message'] and not ('API key' in d['message'] and 'coming soon' in d['message']):
    print('the refusal does not name a way forward (I-16)')
    raise SystemExit
print('ok')
")"

if [ "$FAIL" -eq 0 ]; then
    echo "S251: all smoke checks passed"
else
    exit 1
fi
