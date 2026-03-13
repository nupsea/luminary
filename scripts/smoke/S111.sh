#!/usr/bin/env bash
# S111 smoke: annotation create, list, delete
set -euo pipefail

BASE="http://localhost:8000"

echo "S111 [1/5]: Find a document..."
DOC_ID=$(curl -sf "${BASE}/documents?page_size=1" | python3 -c "
import sys, json
docs = json.load(sys.stdin)['items']
print(docs[0]['id']) if docs else print('')
" 2>/dev/null || true)

if [ -z "$DOC_ID" ]; then
  echo "SKIP: No documents in library"
  exit 0
fi

SEC_ID=$(curl -sf "${BASE}/documents/${DOC_ID}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
secs = d.get('sections', [])
print(secs[0]['id']) if secs else print('')
" 2>/dev/null || true)

if [ -z "$SEC_ID" ]; then
  echo "SKIP: Document has no sections"
  exit 0
fi

echo "S111 [2/5]: POST /annotations -> 201..."
ANN=$(curl -sf -X POST "${BASE}/annotations" \
  -H "Content-Type: application/json" \
  -d "{\"document_id\":\"${DOC_ID}\",\"section_id\":\"${SEC_ID}\",\"selected_text\":\"smoke\",\"start_offset\":0,\"end_offset\":5,\"color\":\"yellow\"}")
ANN_ID=$(echo "$ANN" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
echo "PASS: created annotation $ANN_ID"

echo "S111 [3/5]: GET /annotations?document_id=... -> list contains annotation..."
LIST=$(curl -sf "${BASE}/annotations?document_id=${DOC_ID}")
echo "$LIST" | python3 -c "
import sys, json
items = json.load(sys.stdin)
assert any(i['id'] == '${ANN_ID}' for i in items), 'annotation not found in list'
" || { echo "FAIL"; exit 1; }
echo "PASS"

echo "S111 [4/5]: GET /annotations?document_id=unknown -> empty list..."
EMPTY=$(curl -sf "${BASE}/annotations?document_id=does-not-exist")
echo "$EMPTY" | python3 -c "
import sys, json
items = json.load(sys.stdin)
assert items == [], f'expected empty, got {items}'
" || { echo "FAIL"; exit 1; }
echo "PASS"

echo "S111 [5/5]: DELETE /annotations/{id} -> 204..."
STATUS=$(curl -sf -o /dev/null -w "%{http_code}" -X DELETE "${BASE}/annotations/${ANN_ID}")
[ "$STATUS" = "204" ] || { echo "FAIL: expected 204, got $STATUS"; exit 1; }
echo "PASS"

echo "S111: ALL CHECKS PASSED"
