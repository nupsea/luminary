#!/usr/bin/env bash
set -euo pipefail

BASE="http://localhost:7820"
fail() { echo "FAIL: $1"; exit 1; }

# ---------------------------------------------------------------------------
# 1. POST /notes -- create a note with hierarchical tags
# ---------------------------------------------------------------------------
NOTE_JSON=$(curl -sf -X POST -H 'Content-Type: application/json' \
  -d '{"content":"S162 smoke test note","tags":["science","science/biology","science/biology/genetics"]}' \
  "$BASE/notes")
NOTE_ID=$(echo "$NOTE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "POST /notes with hierarchical tags OK note_id=$NOTE_ID"

# ---------------------------------------------------------------------------
# 2. GET /notes?tag=science -- returns note (prefix match includes children)
# ---------------------------------------------------------------------------
curl -sf "$BASE/notes?tag=science" | python3 -c "
import sys, json
notes = json.load(sys.stdin)
note_id = '$NOTE_ID'
ids = [n['id'] for n in notes]
assert note_id in ids, 'note not returned for tag=science prefix filter'
print('GET /notes?tag=science prefix filter OK (%d notes)' % len(notes))
"

# ---------------------------------------------------------------------------
# 3. GET /notes?tag=science/biology -- returns note (exact and child match)
# ---------------------------------------------------------------------------
curl -sf "$BASE/notes?tag=science/biology" | python3 -c "
import sys, json
notes = json.load(sys.stdin)
note_id = '$NOTE_ID'
ids = [n['id'] for n in notes]
assert note_id in ids, 'note not returned for tag=science/biology filter'
print('GET /notes?tag=science/biology filter OK')
"

# ---------------------------------------------------------------------------
# 4. GET /tags -- returns canonical tags including 'science'
# ---------------------------------------------------------------------------
curl -sf "$BASE/tags" | python3 -c "
import sys, json
tags = json.load(sys.stdin)
assert isinstance(tags, list), 'expected list'
ids = [t['id'] for t in tags]
assert 'science' in ids, 'science not in canonical tags: ' + str(ids[:5])
print('GET /tags flat list OK (%d tags)' % len(tags))
"

# ---------------------------------------------------------------------------
# 5. GET /tags/autocomplete?q=sci -- returns 'science' and children
# ---------------------------------------------------------------------------
curl -sf "$BASE/tags/autocomplete?q=sci" | python3 -c "
import sys, json
results = json.load(sys.stdin)
assert isinstance(results, list), 'expected list'
ids = [t['id'] for t in results]
assert 'science' in ids, 'science not in autocomplete results: ' + str(ids)
print('GET /tags/autocomplete?q=sci OK (%d results)' % len(results))
"

# ---------------------------------------------------------------------------
# 6. GET /tags/tree -- 'science' at top-level with 'science/biology' as child
# ---------------------------------------------------------------------------
curl -sf "$BASE/tags/tree" | python3 -c "
import sys, json
tree = json.load(sys.stdin)
science_node = next((n for n in tree if n['id'] == 'science'), None)
assert science_node is not None, 'science not found in tree'
child_ids = [c['id'] for c in science_node.get('children', [])]
assert 'science/biology' in child_ids, 'science/biology not child of science: ' + str(child_ids)
assert science_node['note_count'] >= 1, 'inclusive note_count should be >= 1'
print('GET /tags/tree nesting OK, inclusive count=%d' % science_node['note_count'])
"

# ---------------------------------------------------------------------------
# 7. GET /tags/{id}/notes -- returns note via tag lookup
# ---------------------------------------------------------------------------
curl -sf "$BASE/tags/science/notes" | python3 -c "
import sys, json
notes = json.load(sys.stdin)
note_id = '$NOTE_ID'
ids = [n['id'] for n in notes]
assert note_id in ids, 'note not returned from GET /tags/science/notes'
print('GET /tags/{id}/notes OK (%d notes)' % len(notes))
"

# ---------------------------------------------------------------------------
# 8. POST /tags -- create a new canonical tag
# ---------------------------------------------------------------------------
TAG_CREATE=$(curl -sf -X POST -H 'Content-Type: application/json' \
  -d '{"id":"smoke-test-tag","display_name":"Smoke Test Tag"}' \
  "$BASE/tags")
echo "$TAG_CREATE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('id') == 'smoke-test-tag', 'id mismatch'
assert d.get('note_count') == 0, 'new tag should have 0 notes'
print('POST /tags OK')
"

# ---------------------------------------------------------------------------
# 9. PUT /tags/{id} -- rename display_name
# ---------------------------------------------------------------------------
curl -sf -X PUT -H 'Content-Type: application/json' \
  -d '{"display_name":"Renamed Smoke Tag"}' \
  "$BASE/tags/smoke-test-tag" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('display_name') == 'Renamed Smoke Tag', 'rename failed: ' + str(d.get('display_name'))
print('PUT /tags/{id} rename OK')
"

# ---------------------------------------------------------------------------
# 10. DELETE /tags/{id} -- 204 when note_count=0
# ---------------------------------------------------------------------------
DEL_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$BASE/tags/smoke-test-tag")
[ "$DEL_STATUS" -eq 204 ] || fail "DELETE /tags expected 204, got $DEL_STATUS"
echo "DELETE /tags/{id} (empty tag) 204 OK"

# ---------------------------------------------------------------------------
# 11. DELETE /tags/{id} -- 409 when note_count > 0
# ---------------------------------------------------------------------------
CONFLICT_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$BASE/tags/science")
[ "$CONFLICT_STATUS" -eq 409 ] || fail "DELETE /tags/science expected 409 (has notes), got $CONFLICT_STATUS"
echo "DELETE /tags/{id} 409 (has notes) OK"

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
curl -s -X DELETE "$BASE/notes/$NOTE_ID" > /dev/null

echo ""
echo "S162 smoke: all checks passed"
