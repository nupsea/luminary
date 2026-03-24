#!/usr/bin/env bash
set -euo pipefail

BASE="http://localhost:7820"
fail() { echo "FAIL: $1"; exit 1; }

# ---------------------------------------------------------------------------
# 1. POST /collections -- create a top-level collection
# ---------------------------------------------------------------------------
COL_JSON=$(curl -sf -X POST -H 'Content-Type: application/json' \
  -d '{"name":"SmokeColl","color":"#FF5733"}' \
  "$BASE/collections")
echo "$COL_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('name') == 'SmokeColl', 'name mismatch'
assert d.get('color') == '#FF5733', 'color mismatch'
assert d.get('parent_collection_id') is None, 'should be top-level'
print('POST /collections OK id=' + d['id'])
"
COL_ID=$(echo "$COL_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# ---------------------------------------------------------------------------
# 2. POST /collections -- create a child collection
# ---------------------------------------------------------------------------
CHILD_JSON=$(curl -sf -X POST -H 'Content-Type: application/json' \
  -d "{\"name\":\"SmokeChild\",\"parent_collection_id\":\"$COL_ID\"}" \
  "$BASE/collections")
echo "$CHILD_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('parent_collection_id') is not None, 'parent_collection_id should be set'
assert d.get('name') == 'SmokeChild', 'child name mismatch'
print('POST /collections (child) OK')
"
CHILD_ID=$(echo "$CHILD_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# ---------------------------------------------------------------------------
# 3. POST /collections -- expect 422 for grandchild (max 2 levels)
# ---------------------------------------------------------------------------
HTTP_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"Grandchild\",\"parent_collection_id\":\"$CHILD_ID\"}" \
  "$BASE/collections")
[ "$HTTP_STATUS" -eq 422 ] || fail "expected 422 for grandchild, got $HTTP_STATUS"
echo "POST /collections grandchild 422 OK"

# ---------------------------------------------------------------------------
# 4. GET /collections/tree -- verify nested structure
# ---------------------------------------------------------------------------
curl -sf "$BASE/collections/tree" | python3 -c "
import sys, json
tree = json.load(sys.stdin)
col_id = '$COL_ID'
child_id = '$CHILD_ID'
parent_node = next((n for n in tree if n['id'] == col_id), None)
assert parent_node is not None, 'parent not found in tree'
child_ids = [c['id'] for c in parent_node.get('children', [])]
assert child_id in child_ids, 'child not nested under parent'
assert all(c['children'] == [] for c in parent_node['children']), 'children should be leaves'
print('GET /collections/tree nested structure OK')
"

# ---------------------------------------------------------------------------
# 5. Create a note and add to collection
# ---------------------------------------------------------------------------
NOTE_JSON=$(curl -sf -X POST -H 'Content-Type: application/json' \
  -d '{"content":"smoke test note for S161"}' \
  "$BASE/notes")
NOTE_ID=$(echo "$NOTE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

curl -sf -X POST -H 'Content-Type: application/json' \
  -d "{\"note_ids\":[\"$NOTE_ID\"]}" \
  "$BASE/collections/$COL_ID/notes" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('added') == 1, 'added count mismatch: ' + str(d)
print('POST /collections/{id}/notes OK')
"

# ---------------------------------------------------------------------------
# 6. POST /collections/{id}/notes again -- idempotent
# ---------------------------------------------------------------------------
curl -sf -X POST -H 'Content-Type: application/json' \
  -d "{\"note_ids\":[\"$NOTE_ID\"]}" \
  "$BASE/collections/$COL_ID/notes" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('added') == 1, 'added should be 1 on duplicate: ' + str(d)
print('POST /collections/{id}/notes idempotent OK')
"

# ---------------------------------------------------------------------------
# 7. GET /notes?collection_id= -- note appears in filtered list
# ---------------------------------------------------------------------------
curl -sf "$BASE/notes?collection_id=$COL_ID" | python3 -c "
import sys, json
notes = json.load(sys.stdin)
note_id = '$NOTE_ID'
ids = [n['id'] for n in notes]
assert note_id in ids, 'note not returned for collection_id filter'
print('GET /notes?collection_id= filter OK (%d notes)' % len(notes))
"

# ---------------------------------------------------------------------------
# 8. Verify note_count in tree reflects membership
# ---------------------------------------------------------------------------
curl -sf "$BASE/collections/tree" | python3 -c "
import sys, json
tree = json.load(sys.stdin)
col_id = '$COL_ID'
node = next((n for n in tree if n['id'] == col_id), None)
assert node is not None, 'collection not in tree'
assert node['note_count'] >= 1, 'note_count should be >= 1, got %d' % node['note_count']
print('note_count in tree OK (%d)' % node['note_count'])
"

# ---------------------------------------------------------------------------
# 9. PUT /collections/{id} -- rename
# ---------------------------------------------------------------------------
curl -sf -X PUT -H 'Content-Type: application/json' \
  -d '{"name":"SmokeCollRenamed"}' \
  "$BASE/collections/$COL_ID" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['name'] == 'SmokeCollRenamed', 'rename failed: ' + d['name']
print('PUT /collections/{id} rename OK')
"

# ---------------------------------------------------------------------------
# 10. DELETE /collections/{id} -- note survives
# ---------------------------------------------------------------------------
DEL_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$BASE/collections/$COL_ID")
[ "$DEL_STATUS" -eq 204 ] || fail "DELETE /collections expected 204, got $DEL_STATUS"

curl -sf "$BASE/notes" | python3 -c "
import sys, json
notes = json.load(sys.stdin)
note_id = '$NOTE_ID'
ids = [n['id'] for n in notes]
assert note_id in ids, 'note was deleted alongside collection -- WRONG'
print('DELETE /collections/{id}: note preserved OK')
"

# ---------------------------------------------------------------------------
# 11. GET /notes/groups -- backward compat still works
# ---------------------------------------------------------------------------
curl -sf "$BASE/notes/groups" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'groups' in d, 'missing groups field'
assert 'tags' in d, 'missing tags field'
print('GET /notes/groups backward-compat OK')
"

# Cleanup
curl -s -X DELETE "$BASE/notes/$NOTE_ID" > /dev/null

echo ""
echo "S161 smoke: all checks passed"
