#!/usr/bin/env bash
# Smoke test for S171: Note-to-note bidirectional links
# Tests POST /notes/{id}/links, GET /notes/{id}/links, DELETE /notes/{id}/links/{target_id},
# and GET /notes/autocomplete endpoints.

set -euo pipefail

BASE="http://localhost:8000"

echo "=== S171 Smoke Test: Note-to-note bidirectional links ==="

# 1. Create source note
echo "1. Create source note"
SRC_RESP=$(curl -s -w "\n%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -d '{"content": "Backpropagation is an algorithm for computing gradients in neural networks.", "tags": []}' \
  "$BASE/notes")
SRC_CODE=$(echo "$SRC_RESP" | tail -1)
SRC_BODY=$(echo "$SRC_RESP" | head -1)

if [ "$SRC_CODE" != "201" ]; then
  echo "FAIL: Expected 201 creating source note, got $SRC_CODE"
  echo "Body: $SRC_BODY"
  exit 1
fi

SRC_ID=$(echo "$SRC_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "  OK: source note id=$SRC_ID"

# 2. Create target note
echo "2. Create target note"
TGT_RESP=$(curl -s -w "\n%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -d '{"content": "Gradient Descent is an optimization method that follows the negative gradient to minimize loss.", "tags": []}' \
  "$BASE/notes")
TGT_CODE=$(echo "$TGT_RESP" | tail -1)
TGT_BODY=$(echo "$TGT_RESP" | head -1)

if [ "$TGT_CODE" != "201" ]; then
  echo "FAIL: Expected 201 creating target note, got $TGT_CODE"
  echo "Body: $TGT_BODY"
  exit 1
fi

TGT_ID=$(echo "$TGT_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "  OK: target note id=$TGT_ID"

# 3. POST /notes/{src}/links to create a link
echo "3. POST /notes/$SRC_ID/links (elaborates -> target)"
LINK_RESP=$(curl -s -w "\n%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -d "{\"target_note_id\": \"$TGT_ID\", \"link_type\": \"elaborates\"}" \
  "$BASE/notes/$SRC_ID/links")
LINK_CODE=$(echo "$LINK_RESP" | tail -1)
LINK_BODY=$(echo "$LINK_RESP" | head -1)

if [ "$LINK_CODE" != "201" ]; then
  echo "FAIL: Expected 201 creating link, got $LINK_CODE"
  echo "Body: $LINK_BODY"
  exit 1
fi

LINK_ID=$(echo "$LINK_BODY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
assert 'id' in data, 'missing id'
assert 'note_id' in data, 'missing note_id'
assert 'link_type' in data, 'missing link_type'
assert data['link_type'] == 'elaborates', 'wrong link_type'
print(data['id'])
")
echo "  OK: link created id=$LINK_ID"

# 4. POST duplicate link -- expect 409
echo "4. POST duplicate link (expect 409)"
DUP_RESP=$(curl -s -w "\n%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -d "{\"target_note_id\": \"$TGT_ID\", \"link_type\": \"elaborates\"}" \
  "$BASE/notes/$SRC_ID/links")
DUP_CODE=$(echo "$DUP_RESP" | tail -1)

if [ "$DUP_CODE" != "409" ]; then
  echo "FAIL: Expected 409 for duplicate link, got $DUP_CODE"
  exit 1
fi
echo "  OK: 409 returned for duplicate"

# 5. GET /notes/{src}/links -- should have 1 outgoing, 0 incoming
echo "5. GET /notes/$SRC_ID/links"
GET_RESP=$(curl -s -w "\n%{http_code}" "$BASE/notes/$SRC_ID/links")
GET_CODE=$(echo "$GET_RESP" | tail -1)
GET_BODY=$(echo "$GET_RESP" | head -1)

if [ "$GET_CODE" != "200" ]; then
  echo "FAIL: Expected 200 getting links, got $GET_CODE"
  echo "Body: $GET_BODY"
  exit 1
fi

OUT_COUNT=$(echo "$GET_BODY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
assert 'outgoing' in data, 'missing outgoing'
assert 'incoming' in data, 'missing incoming'
assert len(data['outgoing']) == 1, f'expected 1 outgoing, got {len(data[\"outgoing\"])}'
assert len(data['incoming']) == 0, f'expected 0 incoming, got {len(data[\"incoming\"])}'
print('outgoing=%d incoming=%d' % (len(data['outgoing']), len(data['incoming'])))
")
echo "  OK: $OUT_COUNT"

# 6. GET /notes/{tgt}/links -- should have 0 outgoing, 1 incoming
echo "6. GET /notes/$TGT_ID/links (expect 0 outgoing, 1 incoming)"
TGT_LINKS=$(curl -s -w "\n%{http_code}" "$BASE/notes/$TGT_ID/links")
TGT_LINKS_CODE=$(echo "$TGT_LINKS" | tail -1)
TGT_LINKS_BODY=$(echo "$TGT_LINKS" | head -1)

if [ "$TGT_LINKS_CODE" != "200" ]; then
  echo "FAIL: Expected 200, got $TGT_LINKS_CODE"
  exit 1
fi

echo "$TGT_LINKS_BODY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
assert len(data['outgoing']) == 0, f'expected 0 outgoing, got {len(data[\"outgoing\"])}'
assert len(data['incoming']) == 1, f'expected 1 incoming, got {len(data[\"incoming\"])}'
print('  OK: backlink visible on target note')
"

# 7. GET /notes/autocomplete?q=Gradient
echo "7. GET /notes/autocomplete?q=Gradient"
AC_RESP=$(curl -s -w "\n%{http_code}" "$BASE/notes/autocomplete?q=Gradient")
AC_CODE=$(echo "$AC_RESP" | tail -1)
AC_BODY=$(echo "$AC_RESP" | head -1)

if [ "$AC_CODE" != "200" ]; then
  echo "FAIL: Expected 200 for autocomplete, got $AC_CODE"
  echo "Body: $AC_BODY"
  exit 1
fi

AC_COUNT=$(echo "$AC_BODY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
assert isinstance(data, list), 'response is not a list'
for item in data:
    assert 'id' in item, 'missing id in autocomplete item'
    assert 'preview' in item, 'missing preview in autocomplete item'
print(len(data))
")
echo "  OK: $AC_COUNT matching notes returned"

# 8. GET /notes/autocomplete?q= (empty) -- returns up to 8 most recent
echo "8. GET /notes/autocomplete?q= (empty query)"
AC_EMPTY=$(curl -s -w "\n%{http_code}" "$BASE/notes/autocomplete?q=")
AC_EMPTY_CODE=$(echo "$AC_EMPTY" | tail -1)
if [ "$AC_EMPTY_CODE" != "200" ]; then
  echo "FAIL: Expected 200 for empty autocomplete, got $AC_EMPTY_CODE"
  exit 1
fi
echo "  OK: empty query returns 200"

# 9. DELETE /notes/{src}/links/{tgt}?link_type=elaborates
echo "9. DELETE /notes/$SRC_ID/links/$TGT_ID?link_type=elaborates"
DEL_RESP=$(curl -s -w "\n%{http_code}" -X DELETE \
  "$BASE/notes/$SRC_ID/links/$TGT_ID?link_type=elaborates")
DEL_CODE=$(echo "$DEL_RESP" | tail -1)

if [ "$DEL_CODE" != "204" ]; then
  echo "FAIL: Expected 204 deleting link, got $DEL_CODE"
  exit 1
fi
echo "  OK: link deleted (204)"

# 10. GET /notes/{src}/links after delete -- 0 outgoing
echo "10. GET /notes/$SRC_ID/links after delete"
POST_DEL=$(curl -s "$BASE/notes/$SRC_ID/links")
echo "$POST_DEL" | python3 -c "
import sys,json
data=json.load(sys.stdin)
assert len(data['outgoing']) == 0, f'expected 0 outgoing after delete, got {len(data[\"outgoing\"])}'
print('  OK: outgoing=0 after delete')
"

# 11. DELETE non-existent link -- expect 404
echo "11. DELETE non-existent link (expect 404)"
NE_DEL=$(curl -s -w "\n%{http_code}" -X DELETE \
  "$BASE/notes/$SRC_ID/links/$TGT_ID?link_type=elaborates")
NE_CODE=$(echo "$NE_DEL" | tail -1)

if [ "$NE_CODE" != "404" ]; then
  echo "FAIL: Expected 404 for non-existent link, got $NE_CODE"
  exit 1
fi
echo "  OK: 404 for non-existent link"

echo ""
echo "=== S171 Smoke Test PASSED ==="
