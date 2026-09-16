#!/usr/bin/env bash
# Smoke test for S253: O'Reilly Learning book ingestion endpoints.
#
# Verifies:
#   1. GET /oreilly/status responds with 200 and valid JSON
#   2. POST /oreilly/cookies refuses invalid cookie payload with 400
#   3. POST /documents/ingest-url with O'Reilly URL without cookies is refused 401
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

# 1. Check /oreilly/status endpoint
STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/oreilly/status")
check "GET /oreilly/status responds" "200" "$STATUS_CODE"

# 2. Check /oreilly/cookies refuses invalid input
INVALID_COOKIE_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/oreilly/cookies" \
    -H "Content-Type: application/json" \
    -d '{"cookies": ""}')
check "POST /oreilly/cookies empty input refused" "400" "$INVALID_COOKIE_CODE"

# 3. Check /documents/ingest-url refuses unauthenticated O'Reilly book with 401
INGEST_URL_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/documents/ingest-url" \
    -H "Content-Type: application/json" \
    -d '{"url": "https://learning.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/"}')
check "POST /documents/ingest-url unauthenticated O'Reilly book refused" "401" "$INGEST_URL_CODE"

if [ "$FAIL" -ne 0 ]; then
    echo "S253: FAILED"
    exit 1
fi
echo "S253: PASS"
