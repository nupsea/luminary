#!/usr/bin/env bash
# Smoke test for S252: who may stop the backend over HTTP.
#
# What this guards: Windows has no SIGTERM, so the desktop shell asks the
# backend to shut down over the port it already owns and only then terminates
# the job -- otherwise `lifespan`'s drain never runs and an ingest in flight is
# cut mid-write. That endpoint exists on every install, and the API is
# unauthenticated on localhost with CSRF deliberately open, so any page in any
# tab can POST to it. Without the shared secret it would be a button for closing
# someone else's app.
#
# Verifies:
#   1. backend is healthy
#   2. POST /setup/shutdown with no token is refused 403
#   3. POST /setup/shutdown with a wrong token is refused 403
#   4. the refusal body does not say whether this install has a token at all
#   5. the backend is still up afterwards
#
# NON-DESTRUCTIVE BY CONSTRUCTION: this never sends a valid token. A smoke run
# that actually stopped the backend would take every later script with it, and
# the accepting path is covered by tests/test_shutdown_endpoint.py.
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

NO_TOKEN=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/setup/shutdown")
check "a request with no token is refused" "403" "$NO_TOKEN"

WRONG=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/setup/shutdown" \
    -H "X-Luminary-Shutdown-Token: not-the-one")
check "a request with a wrong token is refused" "403" "$WRONG"

# The two refusals must be indistinguishable. A different body for "this install
# configured no token" tells a caller whether guessing is worth their time.
BODY_NONE=$(curl -s -X POST "$BASE/setup/shutdown")
BODY_WRONG=$(curl -s -X POST "$BASE/setup/shutdown" -H "X-Luminary-Shutdown-Token: not-the-one")
if [ "$BODY_NONE" = "$BODY_WRONG" ]; then
    echo "PASS: the refusal does not say which half was wrong"
else
    echo "FAIL: refusals differ (none=$BODY_NONE, wrong=$BODY_WRONG)"
    FAIL=1
fi

# The point of the whole script: nothing above may have worked.
STILL_UP=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/health")
check "the backend is still running" "200" "$STILL_UP"

if [ "$FAIL" -eq 0 ]; then
    echo "S252: all smoke checks passed"
else
    exit 1
fi
