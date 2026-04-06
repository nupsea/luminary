#!/usr/bin/env bash
# Smoke test for S176: Notes reader-first layout
# Tests backend contracts the UI depends on.
# Frontend layout changes (Sheet/Drawer, floating bar) are browser-only.

set -euo pipefail

BASE="${LUMINARY_API_BASE:-http://localhost:8000}"

echo "=== S176 smoke: Notes reader-first layout ==="

# 1. GET /notes returns 200 and array
echo "[1] GET /notes..."
NOTES_RESP=$(curl -sf "${BASE}/notes")
echo "${NOTES_RESP}" | python3 -c "import json,sys; data=json.load(sys.stdin); assert isinstance(data, list), f'Expected list, got {type(data)}'; print(f'  OK: {len(data)} notes')"

# 2. GET /notes?tag=someTag returns 200 (tag filter still works at backend)
echo "[2] GET /notes?tag=smoke-tag..."
TAG_RESP=$(curl -sf "${BASE}/notes?tag=smoke-tag")
echo "${TAG_RESP}" | python3 -c "import json,sys; data=json.load(sys.stdin); assert isinstance(data, list), f'Expected list, got {type(data)}'; print(f'  OK: {len(data)} notes with tag smoke-tag')"

# 3. POST /notes creates a note (used by NoteReaderSheet save flow)
echo "[3] POST /notes..."
NOTE_RESP=$(curl -sf -X POST "${BASE}/notes" \
  -H "Content-Type: application/json" \
  -d '{"content":"S176 smoke note","tags":["smoke-tag"],"document_id":null}')
NOTE_ID=$(echo "${NOTE_RESP}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['id'])")
echo "  OK: created note ${NOTE_ID}"

# 4. PATCH /notes/{id} updates content and tags (edit mode in NoteReaderSheet)
echo "[4] PATCH /notes/${NOTE_ID}..."
PATCH_RESP=$(curl -sf -X PATCH "${BASE}/notes/${NOTE_ID}" \
  -H "Content-Type: application/json" \
  -d '{"content":"S176 smoke note updated","tags":["smoke-tag","updated"]}')
echo "${PATCH_RESP}" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['content']=='S176 smoke note updated', f'Content mismatch: {d[\"content\"]}'; print('  OK: patched')"

# 5. GET /notes?tag=smoke-tag now returns the created note
echo "[5] GET /notes?tag=smoke-tag (expects 1+ results)..."
FILTER_RESP=$(curl -sf "${BASE}/notes?tag=smoke-tag")
COUNT=$(echo "${FILTER_RESP}" | python3 -c "import json,sys; data=json.load(sys.stdin); print(len(data))")
[ "${COUNT}" -ge 1 ] || { echo "FAIL: Expected at least 1 note with tag smoke-tag, got ${COUNT}"; exit 1; }
echo "  OK: ${COUNT} note(s) filtered by tag"

# 6. DELETE /notes/{id} deletes the note (delete action in NoteReaderSheet)
echo "[6] DELETE /notes/${NOTE_ID}..."
curl -sf -X DELETE "${BASE}/notes/${NOTE_ID}" -o /dev/null
echo "  OK: deleted"

# 7. GET /collections/tree returns 200 (collections used in edit mode)
echo "[7] GET /collections/tree..."
TREE_RESP=$(curl -sf "${BASE}/collections/tree")
echo "${TREE_RESP}" | python3 -c "import json,sys; data=json.load(sys.stdin); assert isinstance(data, list), f'Expected list, got {type(data)}'; print(f'  OK: {len(data)} top-level collections')"

echo ""
echo "=== S176 smoke PASSED ==="
