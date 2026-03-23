#!/usr/bin/env bash
# Smoke test for S50: Notes tab — POST /notes, GET /notes, PATCH /notes/{id}, DELETE /notes/{id}.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# 1. Create a note
CREATE=$(curl -sf -X POST "${BASE}/notes" \
  -H "Content-Type: application/json" \
  -d '{"content":"smoke test note","tags":[]}')
if [ -z "$CREATE" ]; then
  echo "FAIL: POST /notes returned empty body"
  exit 1
fi

NOTE_ID=$(echo "$CREATE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
if [ -z "$NOTE_ID" ]; then
  echo "FAIL: POST /notes response missing id"
  exit 1
fi

# 2. List notes — created note must appear
LIST=$(curl -sf "${BASE}/notes")
if ! echo "$LIST" | grep -q "smoke test note"; then
  echo "FAIL: GET /notes did not return created note"
  exit 1
fi

# 3. PATCH update
PATCH=$(curl -sf -X PATCH "${BASE}/notes/${NOTE_ID}" \
  -H "Content-Type: application/json" \
  -d '{"content":"smoke test note updated"}')
if ! echo "$PATCH" | grep -q "smoke test note updated"; then
  echo "FAIL: PATCH /notes/{id} did not update content"
  exit 1
fi

# 4. DELETE
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "${BASE}/notes/${NOTE_ID}")
if [ "$HTTP_CODE" != "204" ]; then
  echo "FAIL: DELETE /notes/{id} returned ${HTTP_CODE} (expected 204)"
  exit 1
fi

echo "PASS: Notes CRUD (POST/GET/PATCH/DELETE) all returned expected responses"
