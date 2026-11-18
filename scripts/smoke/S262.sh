#!/usr/bin/env bash
# Smoke test for S262: the libraries surface.
#
# Reads and refusals only: creating, switching, exporting or importing would change the
# library of whoever runs this server.
#
# Verifies:
#   1. GET /libraries answers 200: `default` is listed first, exactly one library is active,
#      and `active` names it
#   2. Switching to a library that does not exist is 404; a name no library can have is 422
#   3. An upload that is not a snapshot is refused (422) and leaves no library behind
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

listed() {
    curl -s "$BASE/libraries" | python3 -c '
import json, sys
body = json.load(sys.stdin)
print(" ".join(item["id"] for item in body["libraries"]))
'
}

# 1. The list and its shape
LIST=$(curl -s -w "\n%{http_code}" "$BASE/libraries")
check "GET /libraries responds" "200" "$(echo "$LIST" | tail -1)"
check "GET /libraries lists default first and one active library" "ok" "$(echo "$LIST" | sed '$d' | python3 -c '
import json, sys
body = json.load(sys.stdin)
items = body["libraries"]
active = [i["id"] for i in items if i["active"]]
ok = (
    items and items[0]["id"] == "default"
    and active == [body["active"]]
    and all(isinstance(i["bytes"], int) for i in items)
)
print("ok" if ok else "bad")
')"
BEFORE=$(listed)

# 2. Switches that cannot happen
check "PUT /libraries/active to a missing library" "404" \
    "$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/libraries/active" \
        -H "Content-Type: application/json" -d '{"library": "smoke-no-such-library"}')"
check "PUT /libraries/active to an impossible name" "422" \
    "$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/libraries/active" \
        -H "Content-Type: application/json" -d '{"library": "../escape"}')"

# 3. An upload that is not a snapshot
NOT_A_SNAPSHOT="$SMOKE_TMP/not-a-snapshot.tar.gz"
printf 'these are my notes' > "$NOT_A_SNAPSHOT"
check "POST /libraries/import of a file that is not a snapshot" "422" \
    "$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/libraries/import" \
        -F "file=@$NOT_A_SNAPSHOT;type=application/gzip" -F "library=smoke-refused-import")"
check "a refused import leaves the library list as it was" "$BEFORE" "$(listed)"

if [ "$FAIL" -ne 0 ]; then
    echo "S262: FAILED"
    exit 1
fi
echo "S262: PASS"
