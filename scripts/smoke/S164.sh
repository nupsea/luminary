#!/usr/bin/env bash
# Smoke test for S164 - Collections UI backend integration
# Tests: GET /collections/tree, POST /collections, PUT /collections/{id},
#        GET /notes (collection_ids field), GET /notes/{id},
#        POST /collections/{id}/notes, DELETE /collections/{id}/notes/{note_id},
#        DELETE /collections/{id}
set -euo pipefail

BASE="http://localhost:7820"
PASS=0
FAIL=0

check() {
  local desc="$1"
  local result="$2"
  if [ "$result" = "true" ]; then
    echo "  PASS: $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc (got: $result)"
    FAIL=$((FAIL + 1))
  fi
}

pycheck() {
  python3 -c "import sys,json; d=json.load(sys.stdin); print(str($1).lower())"
}

echo "=== S164 Smoke Test ==="

# 1. GET /collections/tree returns a list
echo ""
echo "-- GET /collections/tree --"
TREE_RESP=$(curl -sf "$BASE/collections/tree")
IS_LIST=$(echo "$TREE_RESP" | pycheck "isinstance(d, list)")
check "GET /collections/tree returns array" "$IS_LIST"

# 2. POST /collections creates a collection
echo ""
echo "-- POST /collections --"
COL_RESP=$(curl -sf -X POST "$BASE/collections" \
  -H "Content-Type: application/json" \
  -d '{"name":"Smoke Test Collection","color":"#6366F1"}')
COL_ID=$(echo "$COL_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")
COL_NAME=$(echo "$COL_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['name'])")
check "POST /collections returns id" "$([ -n "$COL_ID" ] && echo true || echo false)"
check "POST /collections name matches" "$([ "$COL_NAME" = "Smoke Test Collection" ] && echo true || echo false)"

# 3. GET /collections/tree includes new collection
echo ""
echo "-- GET /collections/tree includes new collection --"
TREE2=$(curl -sf "$BASE/collections/tree")
HAS_COL=$(echo "$TREE2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(any(c['id']=='$COL_ID' for c in d)).lower())")
check "GET /collections/tree includes created collection" "$HAS_COL"

# 4. PUT /collections/{id} renames collection
echo ""
echo "-- PUT /collections/{id} --"
RENAME_RESP=$(curl -sf -X PUT "$BASE/collections/$COL_ID" \
  -H "Content-Type: application/json" \
  -d '{"name":"Renamed Collection"}')
RENAMED=$(echo "$RENAME_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['name'])")
check "PUT /collections/{id} updates name" "$([ "$RENAMED" = "Renamed Collection" ] && echo true || echo false)"

# 5. Create a note and verify GET /notes returns collection_ids field
echo ""
echo "-- GET /notes returns collection_ids field --"
NOTE_RESP=$(curl -sf -X POST "$BASE/notes" \
  -H "Content-Type: application/json" \
  -d '{"content":"Smoke test note for S164"}')
NOTE_ID=$(echo "$NOTE_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")
check "POST /notes returns id" "$([ -n "$NOTE_ID" ] && echo true || echo false)"

NOTES_LIST=$(curl -sf "$BASE/notes")
HAS_COL_IDS=$(echo "$NOTES_LIST" | python3 -c "
import sys, json
notes = json.load(sys.stdin)
note = next((n for n in notes if n['id'] == '$NOTE_ID'), None)
print(str(note is not None and 'collection_ids' in note and isinstance(note['collection_ids'], list)).lower())
")
check "GET /notes includes collection_ids field" "$HAS_COL_IDS"

# 6. GET /notes/{id} returns collection_ids field
echo ""
echo "-- GET /notes/{id} --"
NOTE_GET=$(curl -sf "$BASE/notes/$NOTE_ID")
HAS_COL_IDS2=$(echo "$NOTE_GET" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str('collection_ids' in d and isinstance(d['collection_ids'], list)).lower())")
check "GET /notes/{id} includes collection_ids" "$HAS_COL_IDS2"
EMPTY_IDS=$(echo "$NOTE_GET" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d['collection_ids'] == []).lower())")
check "GET /notes/{id} collection_ids is empty initially" "$EMPTY_IDS"

# 7. POST /collections/{id}/notes adds note to collection
echo ""
echo "-- POST /collections/{id}/notes --"
ADD_RESP=$(curl -sf -X POST "$BASE/collections/$COL_ID/notes" \
  -H "Content-Type: application/json" \
  -d "{\"note_ids\":[\"$NOTE_ID\"]}")
ADDED=$(echo "$ADD_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d['added'] == 1).lower())")
check "POST /collections/{id}/notes added=1" "$ADDED"

# 8. GET /notes/{id} now returns collection_ids with the collection
NOTE_GET2=$(curl -sf "$BASE/notes/$NOTE_ID")
HAS_COL=$(echo "$NOTE_GET2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str('$COL_ID' in d['collection_ids']).lower())")
check "GET /notes/{id} collection_ids includes collection after add" "$HAS_COL"

# 9. GET /notes?collection_id= filters to the collection
echo ""
echo "-- GET /notes?collection_id= filter --"
COL_NOTES=$(curl -sf "$BASE/notes?collection_id=$COL_ID")
IN_LIST=$(echo "$COL_NOTES" | python3 -c "import sys,json; notes=json.load(sys.stdin); print(str(any(n['id']=='$NOTE_ID' for n in notes)).lower())")
check "GET /notes?collection_id= returns note" "$IN_LIST"

# 10. DELETE /collections/{id}/notes/{note_id} removes note from collection
echo ""
echo "-- DELETE /collections/{id}/notes/{note_id} --"
DEL_MEMBER_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE \
  "$BASE/collections/$COL_ID/notes/$NOTE_ID")
check "DELETE /collections/{id}/notes/{note_id} returns 204" "$([ "$DEL_MEMBER_STATUS" = "204" ] && echo true || echo false)"

NOTE_GET3=$(curl -sf "$BASE/notes/$NOTE_ID")
REMOVED=$(echo "$NOTE_GET3" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str('$COL_ID' not in d['collection_ids']).lower())")
check "GET /notes/{id} collection_ids empty after remove" "$REMOVED"

# 11. Cleanup: DELETE /collections/{id}
echo ""
echo "-- DELETE /collections/{id} --"
DEL_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/collections/$COL_ID")
check "DELETE /collections/{id} returns 204" "$([ "$DEL_STATUS" = "204" ] && echo true || echo false)"

# Cleanup: DELETE note
curl -sf -o /dev/null -X DELETE "$BASE/notes/$NOTE_ID" || true

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
