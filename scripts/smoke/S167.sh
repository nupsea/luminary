#!/usr/bin/env bash
# Smoke test for S167 - Tag co-occurrence graph: GET /tags/graph shape, cache, and content.
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

echo "=== S167 Smoke Test ==="

# 1. GET /tags/graph returns correct shape
echo ""
echo "-- GET /tags/graph shape --"
GRAPH_RESP=$(curl -sf "$BASE/tags/graph")
HAS_NODES=$(echo "$GRAPH_RESP" | pycheck "isinstance(d.get('nodes'), list)")
HAS_EDGES=$(echo "$GRAPH_RESP" | pycheck "isinstance(d.get('edges'), list)")
HAS_TS=$(echo "$GRAPH_RESP" | pycheck "isinstance(d.get('generated_at'), (int, float))")
check "GET /tags/graph has nodes array" "$HAS_NODES"
check "GET /tags/graph has edges array" "$HAS_EDGES"
check "GET /tags/graph has generated_at field" "$HAS_TS"

# 2. Cache: two consecutive calls return the same generated_at
echo ""
echo "-- Cache: two calls return same generated_at --"
TS1=$(echo "$GRAPH_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['generated_at'])")
GRAPH_RESP2=$(curl -sf "$BASE/tags/graph")
TS2=$(echo "$GRAPH_RESP2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['generated_at'])")
check "Back-to-back calls return same generated_at" "$([ "$TS1" = "$TS2" ] && echo true || echo false)"

# 3. Create two notes sharing two tags so they appear as co-occurring nodes
SHARED_TAG_A="smoke-cooccur-a-$$"
SHARED_TAG_B="smoke-cooccur-b-$$"

echo ""
echo "-- Creating notes with shared tags to test graph content --"
NOTE1_RESP=$(curl -sf -X POST "$BASE/notes" \
  -H "Content-Type: application/json" \
  -d "{\"content\":\"Smoke note 1\",\"tags\":[\"$SHARED_TAG_A\",\"$SHARED_TAG_B\"]}")
NOTE1_ID=$(echo "$NOTE1_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")
check "POST /notes note1 created" "$([ -n "$NOTE1_ID" ] && echo true || echo false)"

NOTE2_RESP=$(curl -sf -X POST "$BASE/notes" \
  -H "Content-Type: application/json" \
  -d "{\"content\":\"Smoke note 2\",\"tags\":[\"$SHARED_TAG_A\",\"$SHARED_TAG_B\"]}")
NOTE2_ID=$(echo "$NOTE2_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")
check "POST /notes note2 created" "$([ -n "$NOTE2_ID" ] && echo true || echo false)"

# 4. Fetch graph again -- cache should have been invalidated after note writes
echo ""
echo "-- Graph after note creation: cache invalidated, nodes present --"
GRAPH_RESP3=$(curl -sf "$BASE/tags/graph")
TS3=$(echo "$GRAPH_RESP3" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['generated_at'])")
check "generated_at changed after note creation (cache invalidated)" "$([ \"$TS3\" != \"$TS1\" ] && echo true || echo false)"

HAS_TAG_A=$(echo "$GRAPH_RESP3" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(str(any(n['id'] == '$SHARED_TAG_A' for n in d['nodes'])).lower())
")
check "Shared tag A appears in nodes" "$HAS_TAG_A"

HAS_TAG_B=$(echo "$GRAPH_RESP3" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(str(any(n['id'] == '$SHARED_TAG_B' for n in d['nodes'])).lower())
")
check "Shared tag B appears in nodes" "$HAS_TAG_B"

HAS_EDGE=$(echo "$GRAPH_RESP3" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(str(any(
  frozenset([e['tag_a'], e['tag_b']]) == frozenset(['$SHARED_TAG_A', '$SHARED_TAG_B'])
  for e in d['edges']
)).lower())
")
check "Co-occurrence edge between shared tags present" "$HAS_EDGE"

# 5. Edge weight == 2 (appeared together on 2 notes)
EDGE_WEIGHT=$(echo "$GRAPH_RESP3" | python3 -c "
import sys, json
d = json.load(sys.stdin)
edge = next((e for e in d['edges']
  if frozenset([e['tag_a'], e['tag_b']]) == frozenset(['$SHARED_TAG_A', '$SHARED_TAG_B'])), None)
print(str(edge['weight'] if edge else 0))
")
check "Co-occurrence edge weight is 2" "$([ \"$EDGE_WEIGHT\" = \"2\" ] && echo true || echo false)"

# 6. Node fields have expected shape
echo ""
echo "-- Node schema check --"
NODE_SHAPE=$(echo "$GRAPH_RESP3" | python3 -c "
import sys, json
d = json.load(sys.stdin)
node = next((n for n in d['nodes'] if n['id'] == '$SHARED_TAG_A'), None)
if node:
  ok = all(k in node for k in ['id', 'display_name', 'note_count'])
  print(str(ok).lower())
else:
  print('false')
")
check "Node has id, display_name, note_count fields" "$NODE_SHAPE"

# Cleanup
echo ""
echo "-- Cleanup --"
curl -sf -o /dev/null -X DELETE "$BASE/notes/$NOTE1_ID" || true
curl -sf -o /dev/null -X DELETE "$BASE/notes/$NOTE2_ID" || true

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
