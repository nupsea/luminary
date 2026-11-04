#!/usr/bin/env bash
# Smoke test for S261: the connectors surface (#436).
#
# Verifies:
#   1. GET /connectors answers 200 with a `connectors` list, each with the fields the
#      settings card and the upload dialog read
#   2. A connector that is not installed is 404 on status, preview and credentials
#   1b. GET /connectors/catalogue lists entries, each with its licence and source terms
#   3. A link no connector claims is refused by a connector's own routes (422), checked
#      against the first installed connector, if any
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

# 1. The list and its shape
LIST=$(curl -s -w "\n%{http_code}" "$BASE/connectors")
check "GET /connectors responds" "200" "$(echo "$LIST" | tail -1)"
SHAPE=$(echo "$LIST" | sed '$d' | python3 -c '
import json, sys
body = json.load(sys.stdin)
keys = {"name", "label", "version", "licence", "terms", "url_prefixes", "inputs",
        "credentials", "preview", "connected"}
items = body["connectors"]
print("ok" if isinstance(items, list) and all(keys <= set(i) for i in items) else "bad")
print(items[0]["name"] if items else "")
')
check "GET /connectors items carry the fields the UI reads" "ok" "$(echo "$SHAPE" | head -1)"
FIRST=$(echo "$SHAPE" | sed -n 2p)

# 1b. The catalogue, with what is shown before an install. Installing is the user's action.
CAT=$(curl -s -w "\n%{http_code}" "$BASE/connectors/catalogue")
check "GET /connectors/catalogue responds" "200" "$(echo "$CAT" | tail -1)"
check "every catalogue entry shows its licence and its source's terms" "ok" "$(echo "$CAT" | sed '$d' | python3 -c '
import json, sys
items = json.load(sys.stdin)["connectors"]
ok = items and all(i["licence"] and i["terms"]["statement"] and i["terms"]["url"].startswith("https://") for i in items)
print("ok" if ok else "bad")
')"

# 2. An unknown connector
MISSING="not-installed-smoke"
check "GET status of an unknown connector" "404" \
    "$(curl -s -o /dev/null -w "%{http_code}" "$BASE/connectors/$MISSING/status")"
check "POST preview to an unknown connector" "404" \
    "$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/connectors/$MISSING/preview" \
        -H "Content-Type: application/json" -d '{"url": "https://example.com/"}')"
check "PUT credentials of an unknown connector" "404" \
    "$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/connectors/$MISSING/credentials" \
        -H "Content-Type: application/json" -d '{"values": {}}')"

# 3. A link the connector does not claim. Without an installed connector there is
# nothing to ask, and installing one is a user's action, never this script's.
if [ -n "$FIRST" ]; then
    check "POST preview of a link $FIRST does not claim" "422" \
        "$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/connectors/$FIRST/preview" \
            -H "Content-Type: application/json" -d '{"url": "https://unclaimed.invalid/page"}')"
else
    smoke_partial_skip "unclaimed-link refusal: no connector is installed"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "S261: FAILED"
    exit 1
fi
echo "S261: PASS"
