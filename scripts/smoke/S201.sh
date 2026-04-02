#!/usr/bin/env bash
# Smoke test for S201: Tag auto-save normalization + duplicate note dedup
# Exercises: POST /notes (dedup), POST /notes/{id}/suggest-tags (normalization)
set -euo pipefail

BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"
PASS=true

echo "=== S201 Smoke Test ==="

# 1. Create a note
BODY='{"document_id":"smoke-doc-s201","section_id":"sec-1","content":"Test note for S201 smoke","tags":[]}'
TMPFILE=$(mktemp /tmp/s201_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X POST "$BASE/notes" \
  -H "Content-Type: application/json" -d "$BODY")
if [ "$STATUS" -ne 201 ]; then
  echo "FAIL: POST /notes returned $STATUS (expected 201)"
  PASS=false
else
  echo "PASS: POST /notes -> 201"
fi
NOTE_ID=$(python3 -c "import json; print(json.load(open('$TMPFILE'))['id'])")

# 2. Duplicate creation should return same note ID
TMPFILE2=$(mktemp /tmp/s201_dup_XXXXXX.json)
STATUS2=$(curl -s -o "$TMPFILE2" -w "%{http_code}" -X POST "$BASE/notes" \
  -H "Content-Type: application/json" -d "$BODY")
if [ "$STATUS2" -ne 201 ]; then
  echo "FAIL: POST /notes (dedup) returned $STATUS2 (expected 201)"
  PASS=false
else
  NOTE_ID2=$(python3 -c "import json; print(json.load(open('$TMPFILE2'))['id'])")
  if [ "$NOTE_ID" = "$NOTE_ID2" ]; then
    echo "PASS: Duplicate note dedup returned same ID"
  else
    echo "FAIL: Duplicate note returned different ID ($NOTE_ID vs $NOTE_ID2)"
    PASS=false
  fi
fi

# 3. suggest-tags endpoint returns 200
STATUS3=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/notes/$NOTE_ID/suggest-tags")
if [ "$STATUS3" -ne 200 ]; then
  echo "FAIL: POST /notes/{id}/suggest-tags returned $STATUS3 (expected 200)"
  PASS=false
else
  echo "PASS: POST /notes/{id}/suggest-tags -> 200"
fi

# Cleanup
rm -f "$TMPFILE" "$TMPFILE2"

if [ "$PASS" = true ]; then
  echo "=== S201 Smoke: ALL PASSED ==="
  exit 0
else
  echo "=== S201 Smoke: SOME FAILED ==="
  exit 1
fi
