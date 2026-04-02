#!/usr/bin/env bash
# Smoke test for S204: Notes from highlighted text sync state across all surfaces
# Frontend-only fix (query invalidation) -- verify backend contract + tsc.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PORT="${LUMINARY_PORT:-7820}"
BASE="http://localhost:$PORT"
PASS=true

echo "=== S204 Smoke Test ==="

# 1. TypeScript compilation
echo "--- Check 1: tsc --noEmit ---"
if (cd "$REPO_ROOT/frontend" && npx tsc --noEmit 2>&1); then
  echo "PASS: tsc --noEmit exits 0"
else
  echo "FAIL: tsc --noEmit had errors"
  PASS=false
fi

# 2. Verify POST /notes returns full NoteResponse with id, tags, collection_ids
echo "--- Check 2: POST /notes returns full model ---"
TMPFILE=$(mktemp /tmp/s204_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X POST "$BASE/notes" \
  -H "Content-Type: application/json" \
  -d '{"document_id":"smoke-s204-doc","section_id":null,"content":"Smoke test note for S204","tags":["smoke"],"group_name":null}')
if [ "$STATUS" = "200" ] || [ "$STATUS" = "201" ]; then
  # Check required fields exist in response
  for field in id tags collection_ids created_at updated_at; do
    if grep -q "\"$field\"" "$TMPFILE"; then
      echo "  OK: response contains $field"
    else
      echo "  FAIL: response missing $field"
      PASS=false
    fi
  done
  NOTE_ID=$(python3 -c "import json,sys; print(json.load(open('$TMPFILE'))['id'])")
  echo "  Created note: $NOTE_ID"
  # Cleanup: delete the smoke note
  DEL_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/notes/$NOTE_ID")
  echo "  Cleanup: DELETE /notes/$NOTE_ID -> $DEL_STATUS"
else
  echo "  FAIL: POST /notes returned $STATUS (expected 200 or 201)"
  cat "$TMPFILE"
  PASS=false
fi
rm -f "$TMPFILE"

# 3. Verify invalidation code exists in DocumentReader.tsx
echo "--- Check 3: Query invalidation in DocumentReader ---"
DR="$REPO_ROOT/frontend/src/components/reader/DocumentReader.tsx"
for key in "reader-notes" '"notes"' '"notes-groups"' '"collections"'; do
  COUNT=$(grep -c "$key" "$DR" 2>/dev/null || echo 0)
  if [ "$COUNT" -ge 1 ]; then
    echo "  OK: $key invalidation found ($COUNT occurrences)"
  else
    echo "  FAIL: $key invalidation missing"
    PASS=false
  fi
done

if [ "$PASS" = true ]; then
  echo "=== S204 Smoke: ALL PASSED ==="
  exit 0
else
  echo "=== S204 Smoke: SOME FAILED ==="
  exit 1
fi
