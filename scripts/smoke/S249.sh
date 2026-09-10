#!/usr/bin/env bash
# Smoke test for S249: deleting a deck takes the practice runs it emptied, and
# answers with both counts.
#
# What this guards: "Delete all" removed every card and left the runs built on
# them in Session History. Such a row cannot be entered -- I-47 counts only
# planned cards that still exist, so it reports nothing planned and nothing
# outstanding. The client used to end those sessions itself in a second call
# that raced the delete; the delete now does it, and says how many went.
#
# Verifies:
#   1. backend is healthy
#   2. DELETE /flashcards/document/{id} answers 200 with a body, not 204 --
#      a UI cannot state a number it was never told
#   3. the body reports `deleted` and `sessions_removed` separately
#   4. a document with no cards deletes nothing and removes no runs
#   5. bulk-delete carries the same two counts
#
# Non-destructive: every call names a document id that does not exist.
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

check "the delete contract carries both counts" "ok" "$(curl -s "$BASE/openapi.json" | python3 -c "
import sys, json
spec = json.load(sys.stdin)
delete = spec['paths']['/flashcards/document/{document_id}']['delete']
if '204' in delete['responses']:
    print('the document delete still answers 204; the UI cannot report what it removed')
    raise SystemExit
props = spec['components']['schemas']['BulkDeleteResponse']['properties']
missing = [f for f in ('deleted', 'sessions_removed') if f not in props]
print('missing: ' + ', '.join(missing) if missing else 'ok')
")"

UNKNOWN="00000000-0000-4000-8000-$(printf '%012d' "$RANDOM")"

BODY=$(curl -s -w '\n%{http_code}' -X DELETE "$BASE/flashcards/document/$UNKNOWN")
check "an empty deck deletes nothing" "200" "$(echo "$BODY" | tail -n1)"
check "and removes no runs" "0 0" "$(echo "$BODY" | sed '$d' | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d['deleted'], d['sessions_removed'])
")"

BODY=$(curl -s -X POST "$BASE/flashcards/bulk-delete" \
  -H 'Content-Type: application/json' \
  -d "{\"ids\": [\"$UNKNOWN\"]}")
check "bulk-delete reports the same pair" "0 0" "$(echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d['deleted'], d['sessions_removed'])
")"

if [ "$FAIL" -eq 0 ]; then
    echo "ALL SMOKE TESTS PASSED"
    exit 0
fi
exit 1
