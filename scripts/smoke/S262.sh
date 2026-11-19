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
#   4. GET /libraries/destinations lists the export folder first; an archive or destination
#      it does not list is 404, so no request reaches another file
#   5. The default library cannot be removed (422); renaming a missing library is 404
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

# 4. Export destinations
DESTS=$(curl -s -w "\n%{http_code}" "$BASE/libraries/destinations")
check "GET /libraries/destinations responds" "200" "$(echo "$DESTS" | tail -1)"
check "GET /libraries/destinations lists the export folder first" "ok" "$(echo "$DESTS" | sed '$d' | python3 -c '
import json, sys
dests = json.load(sys.stdin)["destinations"]
ok = dests and dests[0]["id"] == "exports" and all(
    isinstance(d["archives"], list) and d["path"] for d in dests
)
print("ok" if ok else "bad")
')"
check "POST /libraries/import-from-folder from an unknown destination" "404" \
    "$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/libraries/import-from-folder" \
        -H "Content-Type: application/json" \
        -d '{"destination": "smoke-nowhere", "name": "x.tar.gz", "library": "smoke-refused"}')"
check "POST /libraries/reveal of a file no destination lists" "404" \
    "$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/libraries/reveal" \
        -H "Content-Type: application/json" -d '{"destination": "exports", "name": "../x.tar.gz"}')"

# 5. Removing and renaming what cannot be
check "DELETE /libraries/default" "422" \
    "$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/libraries/default")"
check "PATCH /libraries of a missing library" "404" \
    "$(curl -s -o /dev/null -w "%{http_code}" -X PATCH "$BASE/libraries/smoke-no-such-library" \
        -H "Content-Type: application/json" -d '{"name": "x"}')"
check "the library list is still as it was" "$BEFORE" "$(listed)"

if [ "$FAIL" -ne 0 ]; then
    echo "S262: FAILED"
    exit 1
fi
echo "S262: PASS"
