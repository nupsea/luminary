#!/usr/bin/env bash
# Smoke test for S122: a YouTube link reaches the core only through the YouTube connector (#467).
#
# With no connector claiming it, the link is refused before any document exists, with what to
# install (the catalogue's `youtube`) and never read as a web article. With the connector
# installed this would download a real talk, so the check is skipped.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

URL="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
CLAIMED=$(curl -s "$BASE/connectors" | python3 -c '
import json, sys
url = sys.argv[1]
items = json.load(sys.stdin)["connectors"]
print("yes" if any(url.startswith(p) for c in items for p in c["url_prefixes"]) else "no")
' "$URL")
if [ "$CLAIMED" = "yes" ]; then
    smoke_partial_skip "a connector claims YouTube links; ingesting would download a real talk"
    echo "S122: PASS (connector installed)"
    exit 0
fi

BODY=$(curl -s -w "\n%{http_code}" -X POST "$BASE/documents/ingest-url" \
    -H "Content-Type: application/json" -d "{\"url\":\"$URL\"}")
CODE=$(echo "$BODY" | tail -1)
[ "$CODE" = "422" ] || { echo "FAIL: S122 unclaimed YouTube link returned HTTP $CODE, not 422"; exit 1; }
echo "$BODY" | sed '$d' | python3 -c '
import json, sys
body = json.load(sys.stdin)
assert body["connector"] == "youtube" and body["catalogue"] is True, body
assert "Settings" in body["detail"] and "audio or video file" in body["detail"], body["detail"]
' || { echo "FAIL: S122 the refusal does not name the connector to install"; exit 1; }
echo "S122: PASS -- an unclaimed YouTube link names the connector to install"
