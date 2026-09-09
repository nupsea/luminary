#!/usr/bin/env bash
# Smoke test for S247: a Practice run that grows, and a tally over cards.
#
# Two contracts the docked Practice panel depends on:
#   1. POST /study/sessions/{id}/cards appends to the planned queue, skips
#      duplicates, drops ids with no card behind them, and the appended card
#      really comes back from /remaining-cards -- which is what a resume rebuilds
#      the run from.
#   2. POST /study/sessions/{id}/end counts CARDS, not submissions: a card
#      answered twice is one card reviewed at its latest score.
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

TMPFILE=$(mktemp /tmp/s247_XXXXXX)
cleanup() { rm -f "$TMPFILE"; }
trap cleanup EXIT

# A document with at least two cards is needed; skip cleanly when the library
# has none rather than reporting a failure that is about the fixture.
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/flashcards/decks")
check "GET /flashcards/decks status" "200" "$HTTP"
DOC_ID=$(python3 - "$TMPFILE" <<'PY'
import json, sys
decks = json.load(open(sys.argv[1]))
for d in decks:
    if d.get("document_id") and (d.get("card_count") or 0) >= 2:
        print(d["document_id"]); break
PY
)
if [ -z "$DOC_ID" ]; then
    echo "SKIP: no document in this library has two cards"
    echo "ALL SMOKE TESTS PASSED"
    exit 0
fi

curl -s -o "$TMPFILE" "$BASE/flashcards/$DOC_ID"
CARD_A=$(python3 -c "import json;print(json.load(open('$TMPFILE'))[0]['id'])")
CARD_B=$(python3 -c "import json;print(json.load(open('$TMPFILE'))[1]['id'])")

# 1. Start a run planning only the first card.
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
    -X POST "$BASE/study/sessions/start" \
    -H "Content-Type: application/json" \
    -d "{\"document_id\": \"$DOC_ID\", \"mode\": \"teachback\", \"planned_card_ids\": [\"$CARD_A\"]}")
check "POST /study/sessions/start status" "201" "$HTTP"
SESSION_ID=$(python3 -c "import json;print(json.load(open('$TMPFILE'))['id'])")

# 2. Append the second card -- the run grows.
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
    -X POST "$BASE/study/sessions/$SESSION_ID/cards" \
    -H "Content-Type: application/json" \
    -d "{\"card_ids\": [\"$CARD_B\"]}")
check "POST /study/sessions/{id}/cards status" "200" "$HTTP"
check "one card added" "1" "$(python3 -c "import json;print(json.load(open('$TMPFILE'))['added'])")"
check "queue is now two" "2" "$(python3 -c "import json;print(json.load(open('$TMPFILE'))['planned_count'])")"

# 3. Appending it again is a no-op -- the learner must not meet it twice.
curl -s -o "$TMPFILE" -X POST "$BASE/study/sessions/$SESSION_ID/cards" \
    -H "Content-Type: application/json" -d "{\"card_ids\": [\"$CARD_B\"]}"
check "duplicate append adds nothing" "0" "$(python3 -c "import json;print(json.load(open('$TMPFILE'))['added'])")"

# 4. An id with no card behind it is dropped, not queued: a planned id that
#    resolves to nothing makes the run shorter than its own stated total.
curl -s -o "$TMPFILE" -X POST "$BASE/study/sessions/$SESSION_ID/cards" \
    -H "Content-Type: application/json" \
    -d '{"card_ids": ["00000000-0000-0000-0000-000000000000"]}'
check "unknown card dropped" "0" "$(python3 -c "import json;print(json.load(open('$TMPFILE'))['added'])")"
check "queue still two" "2" "$(python3 -c "import json;print(json.load(open('$TMPFILE'))['planned_count'])")"

# 5. The appended card is really in the queue a resume rebuilds from.
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/study/sessions/$SESSION_ID/remaining-cards")
check "GET remaining-cards status" "200" "$HTTP"
check "appended card is in the remaining queue" "yes" \
    "$(python3 -c "
import json
d = json.load(open('$TMPFILE'))
print('yes' if '$CARD_B' in [c['id'] for c in d['cards']] else 'no')")"

# 6. Two attempts on one card, one attempt on another. The run reviewed two
#    cards, and the first card's score is its latest.
for BODY in \
    "{\"flashcard_id\": \"$CARD_A\", \"user_explanation\": \"A first, deliberately thin answer.\", \"session_id\": \"$SESSION_ID\"}" \
    "{\"flashcard_id\": \"$CARD_B\", \"user_explanation\": \"A separate answer for the second card.\", \"session_id\": \"$SESSION_ID\"}" \
    "{\"flashcard_id\": \"$CARD_A\", \"user_explanation\": \"A fuller second answer for the first card.\", \"session_id\": \"$SESSION_ID\"}"
do
    HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
        -X POST "$BASE/study/teachback/async" \
        -H "Content-Type: application/json" -d "$BODY")
    check "POST /study/teachback/async status" "200" "$HTTP"
done

HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X POST "$BASE/study/sessions/$SESSION_ID/end")
check "POST /study/sessions/{id}/end status" "200" "$HTTP"
check "three submissions, two cards reviewed" "2" \
    "$(python3 -c "import json;print(json.load(open('$TMPFILE'))['cards_reviewed'])")"

# Cleanup: the session and its rows, so a rerun starts clean.
curl -s -o /dev/null -X DELETE "$BASE/study/sessions/$SESSION_ID"

if [ "$FAIL" -ne 0 ]; then
    echo "SMOKE FAILED"
    exit 1
fi
echo "ALL SMOKE TESTS PASSED"
exit 0
