#!/usr/bin/env bash
set -euo pipefail

BASE="http://localhost:7820"
fail() { echo "FAIL: $1"; exit 1; }

# ---------------------------------------------------------------------------
# 1. POST /notes -- create a note (graph upsert fires in background)
# ---------------------------------------------------------------------------
NOTE_JSON=$(curl -sf -X POST -H 'Content-Type: application/json' \
  -d '{"content":"S163 smoke test: machine learning and neural networks"}' \
  "$BASE/notes")
NOTE_ID=$(echo "$NOTE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "POST /notes OK note_id=$NOTE_ID"

# ---------------------------------------------------------------------------
# 2. GET /notes/{note_id}/entities -- 200, returns a list (possibly empty)
# ---------------------------------------------------------------------------
ENTITIES=$(curl -sf "$BASE/notes/$NOTE_ID/entities")
echo "$ENTITIES" | python3 -c "
import sys, json
data = json.load(sys.stdin)
assert isinstance(data, list), 'expected list, got: ' + str(type(data))
for item in data:
    assert 'name' in item, 'missing name field'
    assert 'type' in item, 'missing type field'
    assert 'confidence' in item, 'missing confidence field'
    assert 'edge_type' in item, 'missing edge_type field'
print('GET /notes/{id}/entities OK (%d entities)' % len(data))
"

# ---------------------------------------------------------------------------
# 3. DELETE /notes/{note_id} -- 204, Kuzu node deleted
# ---------------------------------------------------------------------------
DEL_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$BASE/notes/$NOTE_ID")
[ "$DEL_STATUS" -eq 204 ] || fail "DELETE /notes expected 204, got $DEL_STATUS"
echo "DELETE /notes/$NOTE_ID 204 OK"

# ---------------------------------------------------------------------------
# 4. GET /notes/{note_id}/entities after delete -- 200 with empty list
# ---------------------------------------------------------------------------
ENTITIES_AFTER=$(curl -sf "$BASE/notes/$NOTE_ID/entities")
echo "$ENTITIES_AFTER" | python3 -c "
import sys, json
data = json.load(sys.stdin)
assert isinstance(data, list), 'expected list after delete'
assert len(data) == 0, 'entities should be empty after note delete, got: ' + str(data)
print('GET /notes/{id}/entities after delete OK (empty list confirmed)')
"

echo ""
echo "S163 smoke: all checks passed"
