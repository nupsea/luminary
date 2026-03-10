#!/usr/bin/env bash
# Smoke test for S91: Notes search -- GET /notes/search.

set -euo pipefail
BASE="http://localhost:8000"

# 1. Create a note with searchable content
CREATE=$(curl -sf -X POST "${BASE}/notes" \
  -H "Content-Type: application/json" \
  -d '{"content":"Luminary uses reciprocal rank fusion for hybrid retrieval combining FTS and semantic search.","tags":[]}')
NOTE_ID=$(echo "$CREATE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 2. Search for a term that should match the note via FTS
HTTP_CODE=$(curl -s -o /tmp/s91_search.json -w "%{http_code}" \
  "${BASE}/notes/search?q=reciprocal+rank+fusion")
if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: GET /notes/search returned ${HTTP_CODE} (expected 200)"
  curl -s -X DELETE "${BASE}/notes/${NOTE_ID}" -o /dev/null || true
  exit 1
fi

TOTAL=$(python3 -c "import json; print(json.load(open('/tmp/s91_search.json'))['total'])")
if [ "$TOTAL" -lt 1 ]; then
  echo "FAIL: search returned 0 results (expected >= 1)"
  curl -s -X DELETE "${BASE}/notes/${NOTE_ID}" -o /dev/null || true
  exit 1
fi

# 3. Empty query must return 422
HTTP_422=$(curl -s -o /dev/null -w "%{http_code}" \
  "${BASE}/notes/search?q=")
if [ "$HTTP_422" != "422" ]; then
  echo "FAIL: GET /notes/search?q= returned ${HTTP_422} (expected 422)"
  curl -s -X DELETE "${BASE}/notes/${NOTE_ID}" -o /dev/null || true
  exit 1
fi

# 4. Clean up
curl -s -X DELETE "${BASE}/notes/${NOTE_ID}" -o /dev/null || true

echo "PASS: S91 GET /notes/search returns 200+results and 422 for empty q"
