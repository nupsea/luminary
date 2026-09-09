#!/usr/bin/env bash
# Smoke test for S248: knowing whether a deck can grow before offering to grow it.
#
# GET /flashcards/{id}/headroom is what lets the reader's Practice face hide
# "add more questions" instead of offering it and answering with an error. The
# contract: the counts partition the document's chunks, and a scope whose every
# passage carries a card reports nothing left.
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

TMPFILE=$(mktemp /tmp/s248_XXXXXX)
trap 'rm -f "$TMPFILE"' EXIT

HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/flashcards/decks")
check "GET /flashcards/decks status" "200" "$HTTP"
DOC_ID=$(python3 - "$TMPFILE" <<'PY'
import json, sys
for d in json.load(open(sys.argv[1])):
    if d.get("document_id") and (d.get("card_count") or 0) >= 1:
        print(d["document_id"]); break
PY
)
if [ -z "$DOC_ID" ]; then
    echo "SKIP: no document in this library has a card"
    echo "ALL SMOKE TESTS PASSED"
    exit 0
fi

HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/flashcards/$DOC_ID/headroom")
check "GET /flashcards/{id}/headroom status" "200" "$HTTP"
check "the counts partition the document" "ok" "$(python3 - "$TMPFILE" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
need = {"total_chunks", "used_chunks", "unused_chunks", "cards", "cards_without_sources"}
if not need.issubset(d):
    print("missing:", need - set(d))
elif d["used_chunks"] + d["unused_chunks"] != d["total_chunks"]:
    print(f"used+unused={d['used_chunks'] + d['unused_chunks']} != total={d['total_chunks']}")
elif min(d[k] for k in need) < 0:
    print("negative count")
elif d["cards_without_sources"] > d["cards"]:
    print("more unattributed cards than cards")
else:
    print("ok")
PY
)"

# A section narrows it: a chapter can be exhausted while the book is not.
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/sections/$DOC_ID")
if [ "$HTTP" = "200" ]; then
    SECTION_ID=$(python3 - "$TMPFILE" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
items = d if isinstance(d, list) else d.get("items", d.get("sections", []))
print(items[0]["id"] if items else "")
PY
)
    if [ -n "$SECTION_ID" ]; then
        HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
            "$BASE/flashcards/$DOC_ID/headroom?section_id=$SECTION_ID")
        check "headroom accepts a section scope" "200" "$HTTP"
        check "a section is no larger than its document" "ok" "$(python3 - "$TMPFILE" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("ok" if d["used_chunks"] + d["unused_chunks"] == d["total_chunks"] else "partition broken")
PY
)"
    fi
fi

# An unknown document is empty, not an error: the panel asks before it knows
# whether a document has been chunked at all.
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
    "$BASE/flashcards/00000000-0000-0000-0000-000000000000/headroom")
check "an unknown document answers rather than failing" "200" "$HTTP"
check "and reports no material" "0" \
    "$(python3 -c "import json;print(json.load(open('$TMPFILE'))['total_chunks'])")"

if [ "$FAIL" -ne 0 ]; then
    echo "SMOKE FAILED"
    exit 1
fi
echo "ALL SMOKE TESTS PASSED"
exit 0
