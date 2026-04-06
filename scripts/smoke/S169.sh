#!/usr/bin/env bash
# Smoke test for S169: Collection-based flashcard generation
# Tests GET /flashcards/decks, GET /notes/flashcards/generate/preview, and POST generate
# with a collection_id.

set -euo pipefail

BASE="http://localhost:8000"

echo "=== S169 Smoke Test: Collection-based flashcard generation ==="

# 1. GET /flashcards/decks -- should return 200 and a JSON array
echo "1. GET /flashcards/decks"
DECKS_RESP=$(curl -s -w "\n%{http_code}" "$BASE/flashcards/decks")
HTTP_CODE=$(echo "$DECKS_RESP" | tail -1)
BODY=$(echo "$DECKS_RESP" | head -1)

if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: Expected 200, got $HTTP_CODE"
  echo "Body: $BODY"
  exit 1
fi

if ! echo "$BODY" | grep -q '^\['; then
  echo "FAIL: Response is not a JSON array"
  echo "Body: $BODY"
  exit 1
fi

DECK_COUNT=$(echo "$BODY" | python3 -c "import sys,json; data=json.load(sys.stdin); print(len(data))")
echo "  OK: Response is array ($DECK_COUNT decks)"

# 2. Verify array shape when non-empty
if [ "$DECK_COUNT" -gt "0" ]; then
  echo "2. Verify deck array shape"
  FIRST_DECK=$(echo "$BODY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
d=data[0]
assert 'deck' in d, 'missing deck'
assert 'source_type' in d, 'missing source_type'
assert 'card_count' in d, 'missing card_count'
assert 'document_id' in d, 'missing document_id'
assert 'collection_id' in d, 'missing collection_id'
print('shape ok: deck=%s source_type=%s card_count=%d' % (d['deck'], d['source_type'], d['card_count']))
")
  echo "  OK: $FIRST_DECK"
else
  echo "2. No decks yet -- shape check skipped"
fi

# 3. Get a collection_id from GET /collections/tree
echo "3. GET /collections/tree to find a collection"
COLL_RESP=$(curl -s -w "\n%{http_code}" "$BASE/collections/tree")
COLL_CODE=$(echo "$COLL_RESP" | tail -1)
COLL_BODY=$(echo "$COLL_RESP" | head -1)

if [ "$COLL_CODE" != "200" ]; then
  echo "FAIL: GET /collections/tree returned $COLL_CODE"
  echo "Body: $COLL_BODY"
  exit 1
fi

COLL_COUNT=$(echo "$COLL_BODY" | python3 -c "import sys,json; data=json.load(sys.stdin); print(len(data))")
echo "  OK: $COLL_COUNT collections found"

if [ "$COLL_COUNT" -gt "0" ]; then
  COLL_ID=$(echo "$COLL_BODY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
print(data[0]['id'])
")
  echo "  Using collection_id: $COLL_ID"

  # 4. GET /notes/flashcards/generate/preview?collection_id=...
  echo "4. GET /notes/flashcards/generate/preview?collection_id=$COLL_ID"
  PREV_RESP=$(curl -s -w "\n%{http_code}" \
    "$BASE/notes/flashcards/generate/preview?collection_id=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$COLL_ID'))")")
  PREV_CODE=$(echo "$PREV_RESP" | tail -1)
  PREV_BODY=$(echo "$PREV_RESP" | head -1)

  if [ "$PREV_CODE" != "200" ]; then
    echo "FAIL: Expected 200, got $PREV_CODE"
    echo "Body: $PREV_BODY"
    exit 1
  fi

  PREVIEW_OK=$(echo "$PREV_BODY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
assert 'total_notes' in data, 'missing total_notes'
assert 'already_covered' in data, 'missing already_covered'
print('total_notes=%d already_covered=%d' % (data['total_notes'], data['already_covered']))
")
  echo "  OK: $PREVIEW_OK"

  # 5. POST /notes/flashcards/generate with collection_id (no notes in collection = 0 created)
  echo "5. POST /notes/flashcards/generate with collection_id=$COLL_ID"
  GEN_RESP=$(curl -s -w "\n%{http_code}" -X POST \
    -H "Content-Type: application/json" \
    -d "{\"collection_id\": \"$COLL_ID\", \"count\": 3, \"difficulty\": \"medium\"}" \
    "$BASE/notes/flashcards/generate")
  GEN_CODE=$(echo "$GEN_RESP" | tail -1)
  GEN_BODY=$(echo "$GEN_RESP" | head -1)

  if [ "$GEN_CODE" != "201" ]; then
    echo "FAIL: Expected 201, got $GEN_CODE"
    echo "Body: $GEN_BODY"
    exit 1
  fi

  GEN_OK=$(echo "$GEN_BODY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
assert 'created' in data, 'missing created'
assert 'skipped' in data, 'missing skipped'
assert 'deck' in data, 'missing deck'
print('created=%d skipped=%d deck=%s' % (data['created'], data['skipped'], data['deck']))
")
  echo "  OK: $GEN_OK"
else
  echo "3-5. No collections exist -- testing 404 for preview with nonexistent collection"

  PREV_RESP=$(curl -s -w "\n%{http_code}" \
    "$BASE/notes/flashcards/generate/preview?collection_id=nonexistent-id")
  PREV_CODE=$(echo "$PREV_RESP" | tail -1)
  if [ "$PREV_CODE" != "404" ]; then
    echo "FAIL: Expected 404 for missing collection, got $PREV_CODE"
    exit 1
  fi
  echo "  OK: preview returns 404 for missing collection"
fi

# 6. POST with both collection_id and note_ids -- expect 422
echo "6. POST /notes/flashcards/generate with both collection_id and note_ids (expect 422)"
BOTH_RESP=$(curl -s -w "\n%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -d '{"collection_id": "someid", "note_ids": ["noteid1"]}' \
  "$BASE/notes/flashcards/generate")
BOTH_CODE=$(echo "$BOTH_RESP" | tail -1)
if [ "$BOTH_CODE" != "422" ]; then
  echo "FAIL: Expected 422, got $BOTH_CODE"
  echo "Body: $(echo "$BOTH_RESP" | head -1)"
  exit 1
fi
echo "  OK: 422 returned when both collection_id and note_ids provided"

echo ""
echo "=== S169 Smoke Test PASSED ==="
