#!/usr/bin/env bash
# Smoke test for S165 - Tag browser UI: TagTree, TagManagementPanel, TagAutocomplete
# Tests: GET /tags/tree, GET /tags/autocomplete, PUT /tags/{id} rename,
#        POST /tags/merge, TagAliasModel cleanup, 422 on self-merge
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

echo "=== S165 Smoke Test ==="

# 1. GET /tags/tree returns a list
echo ""
echo "-- GET /tags/tree --"
TREE_RESP=$(curl -sf "$BASE/tags/tree")
IS_LIST=$(echo "$TREE_RESP" | pycheck "isinstance(d, list)")
check "GET /tags/tree returns array" "$IS_LIST"

# 2. GET /tags/autocomplete returns list
echo ""
echo "-- GET /tags/autocomplete --"
AC_RESP=$(curl -sf "$BASE/tags/autocomplete?q=")
IS_LIST2=$(echo "$AC_RESP" | pycheck "isinstance(d, list)")
check "GET /tags/autocomplete?q= returns array" "$IS_LIST2"

# 3. Create a note with a unique tag to test merge
UNIQUE_SRC="smoke-src-$$"
UNIQUE_TGT="smoke-tgt-$$"

echo ""
echo "-- Creating source note and target tag for merge test --"
NOTE_RESP=$(curl -sf -X POST "$BASE/notes" \
  -H "Content-Type: application/json" \
  -d "{\"content\":\"Smoke merge note\",\"tags\":[\"$UNIQUE_SRC\"]}")
NOTE_ID=$(echo "$NOTE_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")
check "POST /notes with source tag succeeded" "$([ -n "$NOTE_ID" ] && echo true || echo false)"

# Create target canonical tag
TGT_RESP=$(curl -sf -X POST "$BASE/tags" \
  -H "Content-Type: application/json" \
  -d "{\"id\":\"$UNIQUE_TGT\",\"display_name\":\"smoke-target\"}")
TGT_CREATED=$(echo "$TGT_RESP" | pycheck "d.get('id') == '$UNIQUE_TGT'")
check "POST /tags target created" "$TGT_CREATED"

# 4. PUT /tags/{id} rename (rename target tag display_name)
echo ""
echo "-- PUT /tags/{id} rename --"
RENAME_RESP=$(curl -sf -X PUT "$BASE/tags/$UNIQUE_TGT" \
  -H "Content-Type: application/json" \
  -d '{"display_name":"smoke-target-renamed"}')
RENAMED=$(echo "$RENAME_RESP" | pycheck "d.get('display_name') == 'smoke-target-renamed'")
check "PUT /tags/{id} updates display_name" "$RENAMED"

# 4b. Create a parent tag and re-parent the target
PARENT_TAG="smoke-parent-$$"
curl -sf -X POST "$BASE/tags" -H "Content-Type: application/json" \
  -d "{\"id\":\"$PARENT_TAG\",\"display_name\":\"smoke-parent\"}" > /dev/null

REPARENT_RESP=$(curl -sf -X PUT "$BASE/tags/$UNIQUE_TGT" \
  -H "Content-Type: application/json" \
  -d "{\"parent_tag\":\"$PARENT_TAG\"}")
REPARENTED=$(echo "$REPARENT_RESP" | pycheck "d.get('parent_tag') == '$PARENT_TAG'")
check "PUT /tags/{id} updates parent_tag" "$REPARENTED"

# 5. GET /tags/autocomplete?q=smoke-src returns source tag
echo ""
echo "-- GET /tags/autocomplete?q=smoke-src-... --"
AC2=$(curl -sf "$BASE/tags/autocomplete?q=$UNIQUE_SRC")
HAS_SRC=$(echo "$AC2" | python3 -c "
import sys, json
results = json.load(sys.stdin)
print(str(any(r['id'] == '$UNIQUE_SRC' for r in results)).lower())
")
check "GET /tags/autocomplete returns source tag" "$HAS_SRC"

# 6. POST /tags/merge merges source into target
echo ""
echo "-- POST /tags/merge --"
MERGE_RESP=$(curl -sf -X POST "$BASE/tags/merge" \
  -H "Content-Type: application/json" \
  -d "{\"source_tag_id\":\"$UNIQUE_SRC\",\"target_tag_id\":\"$UNIQUE_TGT\"}")
AFFECTED=$(echo "$MERGE_RESP" | pycheck "d.get('affected_notes') == 1")
check "POST /tags/merge returns affected_notes=1" "$AFFECTED"

# 7. Verify source tag no longer in canonical list
echo ""
echo "-- Verify source tag deleted after merge --"
LIST_RESP=$(curl -sf "$BASE/tags")
SRC_GONE=$(echo "$LIST_RESP" | python3 -c "
import sys, json
tags = json.load(sys.stdin)
print(str(not any(t['id'] == '$UNIQUE_SRC' for t in tags)).lower())
")
check "Source tag deleted from canonical list" "$SRC_GONE"

TGT_PRESENT=$(echo "$LIST_RESP" | python3 -c "
import sys, json
tags = json.load(sys.stdin)
print(str(any(t['id'] == '$UNIQUE_TGT' for t in tags)).lower())
")
check "Target tag still in canonical list" "$TGT_PRESENT"

# 8. Verify merged note now has target tag
echo ""
echo "-- Verify note tag updated after merge --"
NOTE_GET=$(curl -sf "$BASE/notes/$NOTE_ID")
HAS_TGT=$(echo "$NOTE_GET" | pycheck "'$UNIQUE_TGT' in d.get('tags', [])")
check "Note has target tag after merge" "$HAS_TGT"
SRC_ABSENT=$(echo "$NOTE_GET" | pycheck "'$UNIQUE_SRC' not in d.get('tags', [])")
check "Note no longer has source tag after merge" "$SRC_ABSENT"

# 9. POST /tags/merge with same source and target returns 422
echo ""
echo "-- POST /tags/merge self-merge returns 422 --"
SELF_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/tags/merge" \
  -H "Content-Type: application/json" \
  -d "{\"source_tag_id\":\"$UNIQUE_TGT\",\"target_tag_id\":\"$UNIQUE_TGT\"}")
check "POST /tags/merge self-merge returns 422" "$([ "$SELF_STATUS" = "422" ] && echo true || echo false)"

# Cleanup
curl -sf -o /dev/null -X DELETE "$BASE/notes/$NOTE_ID" || true
curl -sf -o /dev/null -X DELETE "$BASE/tags/$UNIQUE_TGT" || true
curl -sf -o /dev/null -X DELETE "$BASE/tags/$PARENT_TAG" || true

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
