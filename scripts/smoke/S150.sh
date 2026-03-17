#!/usr/bin/env bash
# Smoke test for S150: Passage clips CRUD
# Calls localhost:7820/clips over real HTTP using curl.
set -euo pipefail

BASE="http://localhost:7820"

echo "S150 smoke: POST /clips"
CREATE=$(curl -sf -X POST "$BASE/clips" \
  -H "Content-Type: application/json" \
  -d '{"document_id":"smoke-doc-1","section_id":"sec-1","section_heading":"Chapter 1","selected_text":"A great passage about monads.","user_note":""}')
echo "$CREATE" | grep -q '"id"' || { echo "FAIL: POST /clips did not return id"; exit 1; }
CLIP_ID=$(echo "$CREATE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "  created clip id=$CLIP_ID"

echo "S150 smoke: GET /clips"
LIST=$(curl -sf "$BASE/clips")
echo "$LIST" | grep -q "$CLIP_ID" || { echo "FAIL: GET /clips did not include new clip"; exit 1; }

echo "S150 smoke: GET /clips?document_id=smoke-doc-1"
FILTERED=$(curl -sf "$BASE/clips?document_id=smoke-doc-1")
echo "$FILTERED" | grep -q "smoke-doc-1" || { echo "FAIL: GET /clips?document_id filter failed"; exit 1; }

echo "S150 smoke: PATCH /clips/$CLIP_ID"
PATCHED=$(curl -sf -X PATCH "$BASE/clips/$CLIP_ID" \
  -H "Content-Type: application/json" \
  -d '{"user_note":"My smoke note"}')
echo "$PATCHED" | grep -q "My smoke note" || { echo "FAIL: PATCH did not update user_note"; exit 1; }

echo "S150 smoke: DELETE /clips/$CLIP_ID"
DEL_STATUS=$(curl -sf -o /dev/null -w "%{http_code}" -X DELETE "$BASE/clips/$CLIP_ID")
[ "$DEL_STATUS" = "204" ] || { echo "FAIL: DELETE returned $DEL_STATUS not 204"; exit 1; }

echo "S150 smoke: second DELETE returns 404"
DEL2_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/clips/$CLIP_ID")
[ "$DEL2_STATUS" = "404" ] || { echo "FAIL: second DELETE returned $DEL2_STATUS not 404"; exit 1; }

echo "S150 smoke: PASS"
