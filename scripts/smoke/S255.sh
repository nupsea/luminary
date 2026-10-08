#!/usr/bin/env bash
# Smoke test for S255: device auth and pairing, the 0.16.0 exit gate, on the wire.
#
# What this guards: any page in any tab could POST to the backend. A browser
# request is now tokenless only from the app's own origin; any other origin needs
# a paired device's token, and a revoked token is refused.
#
# Verifies:
#   1. backend is healthy
#   2. a foreign origin is refused (401) without a token
#   3. the app (no Origin) can show a pairing code
#   4. a foreign origin pairs with that code and gets a token
#   5. that token admits the foreign origin
#   6. the device is listed, then revoked
#   7. the revoked token is refused
#
# Leaves one revoked device named "smoke-S255" in the list.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

FAIL=0
EVIL="Origin: https://evil.example"

check() {
    local desc="$1" expected="$2" actual="$3"
    if [ "$actual" != "$expected" ]; then
        echo "FAIL: $desc (expected=$expected, actual=$actual)"
        FAIL=1
    else
        echo "PASS: $desc"
    fi
}

json_field() {
    python3 -c "import json,sys;print(json.load(sys.stdin)['$1'])"
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/health")
check "backend healthy" "200" "$HTTP"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -H "$EVIL" "$BASE/tags")
check "an unpaired origin is refused" "401" "$HTTP"

CODE=$(curl -sf -X POST "$BASE/devices/pairing-code" | json_field code)
check "the app shows a pairing code" "9" "${#CODE}"

PAIRED=$(curl -sf -X POST -H "$EVIL" -H "Content-Type: application/json" \
    -d "{\"code\":\"$CODE\",\"name\":\"smoke-S255\"}" "$BASE/devices/pair")
TOKEN=$(echo "$PAIRED" | json_field token)
DEVICE_ID=$(echo "$PAIRED" | json_field device_id)
check "pairing returns a token" "lum_" "${TOKEN:0:4}"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -H "$EVIL" -H "Authorization: Bearer $TOKEN" "$BASE/tags")
check "the paired origin is admitted" "200" "$HTTP"

LISTED=$(curl -sf "$BASE/devices" | python3 -c "
import json, sys
print(any(d['id'] == '$DEVICE_ID' for d in json.load(sys.stdin)))")
check "the device is listed" "True" "$LISTED"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/devices/$DEVICE_ID")
check "the device is revoked" "204" "$HTTP"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -H "$EVIL" -H "Authorization: Bearer $TOKEN" "$BASE/tags")
check "a revoked token is refused" "401" "$HTTP"

exit $FAIL
