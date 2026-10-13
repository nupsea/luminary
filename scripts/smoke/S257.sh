#!/usr/bin/env bash
# Smoke test for S257: transcript vocabulary and term fixes, on the wire.
#
# What this guards: speech recognition misspells names ("LANs-dv" for LanceDB);
# the learner keeps a vocabulary every import is corrected toward, and fixes a
# term across a transcript and its indexes.
#
# Verifies:
#   1. backend is healthy
#   2. the vocabulary round-trips, de-duplicated (the stored list is restored after)
#   3. a fix for an unknown document is 404, and an empty term is refused (422)
#
# Never fixes a real document: a fix rewrites that transcript's text.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

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

ORIGINAL=$(curl -sf "$BASE/settings/transcript-vocabulary")
restore() {
    curl -s -o /dev/null -X PUT -H "Content-Type: application/json" -d "$ORIGINAL" \
        "$BASE/settings/transcript-vocabulary"
}
trap restore EXIT

SAVED=$(curl -sf -X PUT -H "Content-Type: application/json" \
    -d '{"terms":[" LanceDB ","lancedb","Kimi  K3"]}' "$BASE/settings/transcript-vocabulary" \
    | python3 -c "import json, sys; print(json.load(sys.stdin)['terms'])")
check "vocabulary saved de-duplicated" "['LanceDB', 'Kimi K3']" "$SAVED"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" \
    -d '{"heard":"LANs-dv","term":"LanceDB","remember":false}' \
    "$BASE/documents/smoke-no-such-document/transcript/corrections")
check "a fix for an unknown document is 404" "404" "$HTTP"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" \
    -d '{"heard":"LANs-dv","term":"  ","remember":false}' \
    "$BASE/documents/smoke-no-such-document/transcript/corrections")
check "an empty correction is refused" "422" "$HTTP"

exit $FAIL
