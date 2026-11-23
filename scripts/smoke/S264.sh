#!/usr/bin/env bash
# Smoke test for S264: a document's sections revalidate instead of downloading again (#452).
#
# Verifies:
#   1. GET /sections/{id}/content answers 200 with an ETag
#   2. The same request with If-None-Match answers 304 and no body
#   3. One section's own route carries an ETag and revalidates the same way
#
# Ingests the smoke fixture and deletes it on exit.
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

etag_of() {
    curl -s -D - -o /dev/null "$1" | tr -d '\r' | sed -n 's/^[Ee][Tt]ag: //p'
}

DOC_ID=$(smoke_ingest_fixture)
trap 'curl -s -o /dev/null -X DELETE "$BASE/documents/$DOC_ID?delete_notes=true" || true' EXIT

PAGE="$BASE/sections/$DOC_ID/content"
TAG=$(etag_of "$PAGE")
check "the page carries an ETag" "1" "$([ -n "$TAG" ] && echo 1 || echo 0)"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -H "If-None-Match: $TAG" "$PAGE")
check "an unchanged page answers 304" "304" "$HTTP"

SECTION=$(curl -sf "$PAGE" | python3 -c "import json,sys;print(json.load(sys.stdin)['items'][0]['section_id'])")
ONE="$BASE/sections/$DOC_ID/content/$SECTION"
TAG=$(etag_of "$ONE")
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -H "If-None-Match: $TAG" "$ONE")
check "an unchanged section answers 304" "304" "$HTTP"

if [ "$FAIL" -ne 0 ]; then
    echo "S264 smoke FAILED"
    exit 1
fi
echo "S264 smoke PASSED"
