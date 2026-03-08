#!/usr/bin/env bash
# Smoke test for S84: UI responsiveness — lazy-load core pages, fix Notes stale time,
# remove duplicate SSE calls via useRef Set guard.
#
# Backend checks only (frontend bundle changes are not testable via curl):
# 1. GET /notes — returns 200 (Notes staleTime backend side unaffected)
# 2. POST /notes — create a note, verify 201 / 200
# 3. PATCH /notes/{id} — inline edit, verify updated content
# 4. DELETE /notes/{id} — cleanup
set -euo pipefail

BASE="${BACKEND_URL:-http://localhost:8000}"

# ---- (1) GET /notes returns 200 ----
STATUS=$(curl -so /dev/null -w "%{http_code}" "$BASE/notes")
[ "$STATUS" = "200" ] || { echo "FAIL: GET /notes returned $STATUS"; exit 1; }
echo "PASS: GET /notes → 200"

# ---- (2) POST /notes creates a note ----
NOTE=$(curl -sf -X POST "$BASE/notes" \
  -H "Content-Type: application/json" \
  -d '{"content": "S84 smoke test note", "tags": ["smoke"], "document_id": null}')
NOTE_ID=$(python3 -c "import sys,json; print(json.loads('$NOTE')['id'])")
echo "PASS: POST /notes → id=$NOTE_ID"

# ---- (3) PATCH /notes/{id} updates the note ----
PATCHED=$(curl -sf -X PATCH "$BASE/notes/$NOTE_ID" \
  -H "Content-Type: application/json" \
  -d '{"content": "S84 smoke test note — edited"}')
python3 -c "
import sys, json
note = json.loads('$PATCHED')
assert 'edited' in note.get('content', ''), f\"FAIL: content not updated: {note.get('content')!r}\"
print('PASS: PATCH /notes/$NOTE_ID → content updated')
"

# ---- (4) DELETE /notes/{id} cleanup ----
HTTP_DEL=$(curl -so /dev/null -w "%{http_code}" -X DELETE "$BASE/notes/$NOTE_ID")
[ "$HTTP_DEL" = "200" ] || [ "$HTTP_DEL" = "204" ] || {
  echo "FAIL: DELETE /notes/$NOTE_ID returned $HTTP_DEL"; exit 1
}
echo "PASS: DELETE /notes/$NOTE_ID → $HTTP_DEL"

echo "S84 smoke test PASSED"
