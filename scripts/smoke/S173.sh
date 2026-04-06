#!/usr/bin/env bash
# Smoke test for S173: Collection health report
# Tests GET /collections/{id}/health and POST /collections/{id}/health/archive-stale

set -euo pipefail
BASE="${API_BASE:-http://localhost:8000}"

echo "=== S173 Smoke Test ==="

# Create a collection
echo "[1] Creating test collection..."
COLL=$(curl -sf -X POST "$BASE/collections" \
  -H "Content-Type: application/json" \
  -d '{"name":"SmokeTestColl173","color":"#6366F1"}')
COLL_ID=$(echo "$COLL" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
COLL_NAME=$(echo "$COLL" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")
echo "  collection id=$COLL_ID name=$COLL_NAME"

# Create a note
echo "[2] Creating test note..."
NOTE=$(curl -sf -X POST "$BASE/notes" \
  -H "Content-Type: application/json" \
  -d '{"content":"Smoke test note for collection health"}')
NOTE_ID=$(echo "$NOTE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "  note id=$NOTE_ID"

# Add note to collection
echo "[3] Adding note to collection..."
curl -sf -X POST "$BASE/collections/$COLL_ID/notes" \
  -H "Content-Type: application/json" \
  -d "{\"note_ids\":[\"$NOTE_ID\"]}" > /dev/null
echo "  done"

# GET /collections/{id}/health
echo "[4] GET /collections/$COLL_ID/health..."
HEALTH=$(curl -sf "$BASE/collections/$COLL_ID/health")
echo "  response: $HEALTH"

# Assert required keys present
python3 - <<EOF
import sys, json
data = json.loads('''$HEALTH''')
required = ["collection_id","collection_name","cohesion_score","note_count",
            "orphaned_notes","uncovered_notes","stale_notes","hotspot_tags"]
missing = [k for k in required if k not in data]
if missing:
    print(f"FAIL: missing keys: {missing}", file=sys.stderr)
    sys.exit(1)
assert data["collection_id"] == "$COLL_ID", f"collection_id mismatch: {data['collection_id']}"
assert data["collection_name"] == "$COLL_NAME", f"name mismatch"
assert data["note_count"] == 1, f"expected note_count=1, got {data['note_count']}"
print("  All required keys present and note_count=1 -- OK")
EOF

# POST /collections/{id}/health/archive-stale (no stale notes, should return archived=0)
echo "[5] POST /collections/$COLL_ID/health/archive-stale..."
ARCHIVE=$(curl -sf -X POST "$BASE/collections/$COLL_ID/health/archive-stale")
echo "  response: $ARCHIVE"
python3 - <<EOF
import sys, json
data = json.loads('''$ARCHIVE''')
assert "archived" in data, f"missing 'archived' key: {data}"
assert isinstance(data["archived"], int), f"expected int, got {type(data['archived'])}"
print(f"  archived={data['archived']} -- OK")
EOF

# Cleanup
echo "[6] Cleaning up..."
curl -sf -X DELETE "$BASE/collections/$COLL_ID" > /dev/null || true

echo ""
echo "=== S173 PASSED ==="
