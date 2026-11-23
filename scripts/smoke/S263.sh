#!/usr/bin/env bash
# Smoke test for S263: the change feed a paired client syncs from (#450), on the wire.
#
# Verifies:
#   1. GET /changes answers 200 with an epoch, a cursor and a list
#   2. A note created after the cursor appears as an upsert, and its deletion as a delete
#   3. A cursor from another epoch is told to resync
#   4. A limit outside 1..1000 is refused (422)
#
# Creates one note and deletes it.
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

field() {
    python3 -c "import json,sys;print(json.load(sys.stdin)['$1'])"
}

ops() {
    python3 -c "import json,sys;print(' '.join(c['op'] for c in json.load(sys.stdin)['changes'] if c['entity_id']=='$1'))"
}

START=$(curl -sf "$BASE/changes")
EPOCH=$(echo "$START" | field epoch)
NEXT=$(echo "$START" | field next)
check "feed answers with an epoch" "36" "${#EPOCH}"

NOTE=$(curl -sf -X POST "$BASE/notes" -H "Content-Type: application/json" \
    -d '{"content": "S263 smoke note: the change feed."}' | field id)
check "a new note is an upsert after the cursor" "upsert" \
    "$(curl -sf "$BASE/changes?epoch=$EPOCH&since=$NEXT" | ops "$NOTE")"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/notes/$NOTE")
check "the note is deleted" "204" "$HTTP"
check "its deletion replaces the upsert" "delete" \
    "$(curl -sf "$BASE/changes?epoch=$EPOCH&since=$NEXT" | ops "$NOTE")"

check "another epoch resyncs" "True" \
    "$(curl -sf "$BASE/changes?epoch=another&since=$NEXT" | field resync)"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/changes?limit=0")
check "limit 0 is refused" "422" "$HTTP"

if [ "$FAIL" -ne 0 ]; then
    echo "S263 smoke FAILED"
    exit 1
fi
echo "S263 smoke PASSED"
