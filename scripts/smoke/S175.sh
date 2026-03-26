#!/usr/bin/env bash
# Smoke test for S175: Multi-document notes
# Tests that notes can be linked to multiple source documents via NoteSourceModel pivot.

set -euo pipefail
BASE="${API_BASE:-http://localhost:8000}"

echo "=== S175 Smoke Test ==="

# Use two fake but stable document IDs for smoke (no real docs needed -- pivot has no FK to docs)
DOC_ID_1="smoke-doc-s175-$(date +%s)-1"
DOC_ID_2="smoke-doc-s175-$(date +%s)-2"

# [1] POST /notes with source_document_ids
echo "[1] POST /notes with source_document_ids=[$DOC_ID_1, $DOC_ID_2]..."
NOTE=$(curl -sf -X POST "$BASE/notes" \
  -H "Content-Type: application/json" \
  -d "{\"content\":\"S175 smoke test note\",\"tags\":[],\"source_document_ids\":[\"$DOC_ID_1\",\"$DOC_ID_2\"]}")
NOTE_ID=$(echo "$NOTE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "  note id=$NOTE_ID"

# Assert source_document_ids returned in POST response
python3 - <<EOF
import sys, json
data = json.loads('''$NOTE''')
assert "source_document_ids" in data, f"missing source_document_ids in POST response"
assert "$DOC_ID_1" in data["source_document_ids"], f"$DOC_ID_1 not in source_document_ids"
assert "$DOC_ID_2" in data["source_document_ids"], f"$DOC_ID_2 not in source_document_ids"
print(f"  source_document_ids={data['source_document_ids']} -- OK")
EOF

# [2] GET /notes/{id} includes source_document_ids
echo "[2] GET /notes/$NOTE_ID..."
GET_NOTE=$(curl -sf "$BASE/notes/$NOTE_ID")
python3 - <<EOF
import sys, json
data = json.loads('''$GET_NOTE''')
assert "source_document_ids" in data, f"missing source_document_ids in GET /notes/{id}"
assert "$DOC_ID_1" in data["source_document_ids"], f"$DOC_ID_1 not in GET response"
assert "$DOC_ID_2" in data["source_document_ids"], f"$DOC_ID_2 not in GET response"
print(f"  source_document_ids={data['source_document_ids']} -- OK")
EOF

# [3] GET /notes?document_id={DOC_ID_1} returns the note via pivot
echo "[3] GET /notes?document_id=$DOC_ID_1..."
LIST_1=$(curl -sf "$BASE/notes?document_id=$DOC_ID_1")
python3 - <<EOF
import sys, json
notes = json.loads('''$LIST_1''')
ids = [n["id"] for n in notes]
assert "$NOTE_ID" in ids, f"note $NOTE_ID not found in list for DOC_ID_1. ids={ids}"
print(f"  found note in list for DOC_ID_1 -- OK")
EOF

# [4] GET /notes?document_id={DOC_ID_2} also returns the note
echo "[4] GET /notes?document_id=$DOC_ID_2..."
LIST_2=$(curl -sf "$BASE/notes?document_id=$DOC_ID_2")
python3 - <<EOF
import sys, json
notes = json.loads('''$LIST_2''')
ids = [n["id"] for n in notes]
assert "$NOTE_ID" in ids, f"note $NOTE_ID not found in list for DOC_ID_2. ids={ids}"
print(f"  found note in list for DOC_ID_2 -- OK")
EOF

# [5] PATCH /notes/{id} to remove DOC_ID_1
echo "[5] PATCH /notes/$NOTE_ID to keep only DOC_ID_2..."
PATCHED=$(curl -sf -X PATCH "$BASE/notes/$NOTE_ID" \
  -H "Content-Type: application/json" \
  -d "{\"source_document_ids\":[\"$DOC_ID_2\"]}")
python3 - <<EOF
import sys, json
data = json.loads('''$PATCHED''')
assert "$DOC_ID_2" in data["source_document_ids"], f"$DOC_ID_2 should still be present"
assert "$DOC_ID_1" not in data["source_document_ids"], f"$DOC_ID_1 should be removed"
print(f"  source_document_ids after patch={data['source_document_ids']} -- OK")
EOF

# [6] Cleanup
echo "[6] Cleanup: DELETE /notes/$NOTE_ID..."
curl -sf -X DELETE "$BASE/notes/$NOTE_ID" > /dev/null || true

echo ""
echo "=== S175 PASSED ==="
