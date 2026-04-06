#!/usr/bin/env bash
# Smoke test for S206: Flashcard search FTS5 fix
# Full user journey: create card -> keyword search -> find it
set -euo pipefail

BASE="${LUMINARY_URL:-http://localhost:7820}"
KEYWORD="s206smokezyxwv"

echo "=== S206 Smoke Test ==="

# 1. Create a trace flashcard with a unique keyword
echo "--- Test 1: POST /flashcards/create-trace ---"
TMPFILE=$(mktemp /tmp/s206_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
  -X POST "$BASE/flashcards/create-trace" \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"What is ${KEYWORD} in physics?\", \"answer\": \"A test concept for ${KEYWORD} validation.\", \"source_excerpt\": \"Smoke test excerpt\"}")
if [ "$STATUS" -ne 201 ]; then
  echo "FAIL: expected 201, got $STATUS"
  cat "$TMPFILE"
  rm -f "$TMPFILE"
  exit 1
fi
CARD_ID=$(python3 -c "import json; print(json.load(open('$TMPFILE'))['id'])")
echo "PASS: created trace flashcard $CARD_ID"
rm -f "$TMPFILE"

# 2. Search for the unique keyword -- should find the card
echo "--- Test 2: GET /flashcards/search?query=${KEYWORD} ---"
TMPFILE2=$(mktemp /tmp/s206_XXXXXX.json)
STATUS2=$(curl -s -o "$TMPFILE2" -w "%{http_code}" "$BASE/flashcards/search?query=${KEYWORD}")
if [ "$STATUS2" -ne 200 ]; then
  echo "FAIL: expected 200, got $STATUS2"
  cat "$TMPFILE2"
  rm -f "$TMPFILE2"
  exit 1
fi
TOTAL=$(python3 -c "import json; print(json.load(open('$TMPFILE2'))['total'])")
if [ "$TOTAL" -lt 1 ]; then
  echo "FAIL: expected total >= 1, got $TOTAL"
  cat "$TMPFILE2"
  rm -f "$TMPFILE2"
  exit 1
fi
FOUND=$(python3 -c "import json; ids=[i['id'] for i in json.load(open('$TMPFILE2'))['items']]; print('yes' if '$CARD_ID' in ids else 'no')")
if [ "$FOUND" != "yes" ]; then
  echo "FAIL: card $CARD_ID not found in search results"
  cat "$TMPFILE2"
  rm -f "$TMPFILE2"
  exit 1
fi
echo "PASS: keyword search found the created card"
rm -f "$TMPFILE2"

# 3. Search with special characters (should not 500)
echo "--- Test 3: GET /flashcards/search with special chars ---"
TMPFILE3=$(mktemp /tmp/s206_XXXXXX.json)
STATUS3=$(curl -s -o "$TMPFILE3" -w "%{http_code}" --get --data-urlencode "query=(hello) AND \"world\"" "$BASE/flashcards/search")
if [ "$STATUS3" -ne 200 ]; then
  echo "FAIL: expected 200 for special char query, got $STATUS3"
  cat "$TMPFILE3"
  rm -f "$TMPFILE3"
  exit 1
fi
echo "PASS: special character query returns 200"
rm -f "$TMPFILE3"

# 4. Search with filter combination
echo "--- Test 4: GET /flashcards/search with query + fsrs_state filter ---"
TMPFILE4=$(mktemp /tmp/s206_XXXXXX.json)
STATUS4=$(curl -s -o "$TMPFILE4" -w "%{http_code}" "$BASE/flashcards/search?query=${KEYWORD}&fsrs_state=new")
if [ "$STATUS4" -ne 200 ]; then
  echo "FAIL: expected 200, got $STATUS4"
  cat "$TMPFILE4"
  rm -f "$TMPFILE4"
  exit 1
fi
TOTAL4=$(python3 -c "import json; print(json.load(open('$TMPFILE4'))['total'])")
if [ "$TOTAL4" -lt 1 ]; then
  echo "FAIL: expected total >= 1 with filter, got $TOTAL4"
  cat "$TMPFILE4"
  rm -f "$TMPFILE4"
  exit 1
fi
echo "PASS: search with query + filter returns results"
rm -f "$TMPFILE4"

# Cleanup: delete the test card
echo "--- Cleanup: DELETE /flashcards/$CARD_ID ---"
curl -s -o /dev/null -w "" -X DELETE "$BASE/flashcards/$CARD_ID"

echo ""
echo "=== S206 Smoke Test PASSED ==="
