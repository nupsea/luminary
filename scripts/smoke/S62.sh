#!/usr/bin/env bash
# Smoke test for S62: tag storage and filter
# Tests PATCH /documents/{id}/tags and GET /documents?tag=X
set -euo pipefail

BASE="${BACKEND_URL:-http://localhost:7820}"

# Create a document via ingest (we need a real endpoint, use a tiny text file)
INGEST_RESP=$(curl -sf -X POST "$BASE/documents/ingest" \
  -F "file=@/dev/stdin;filename=smoke_s62.txt" <<< "Tag smoke test document for S62.")
DOC_ID=$(echo "$INGEST_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['document_id'])")
echo "Created document: $DOC_ID"

# PATCH tags
PATCH_RESP=$(curl -sf -X PATCH "$BASE/documents/$DOC_ID/tags" \
  -H "Content-Type: application/json" \
  -d '{"tags": ["smoke-s62"]}')
echo "PATCH tags response: $PATCH_RESP"
echo "$PATCH_RESP" | python3 -c "
import sys, json
body = json.load(sys.stdin)
assert isinstance(body['tags'], list), f'tags must be list, got {type(body[\"tags\"])}'
assert body['tags'] == ['smoke-s62'], f'unexpected tags: {body[\"tags\"]}'
print('PASS: PATCH returns list')
"

# GET /documents?tag=smoke-s62 — should include our document
LIST_RESP=$(curl -sf "$BASE/documents?tag=smoke-s62")
echo "$LIST_RESP" | python3 -c "
import sys, json
body = json.load(sys.stdin)
ids = [i['id'] for i in body['items']]
assert '$DOC_ID' in ids, f'document $DOC_ID not in tagged results: {ids}'
print('PASS: tag filter returns matching doc')
"

# GET /documents?tag=smoke — must NOT match (smoke is substring of smoke-s62, but not exact element)
SUBSTR_RESP=$(curl -sf "$BASE/documents?tag=smoke")
echo "$SUBSTR_RESP" | python3 -c "
import sys, json
body = json.load(sys.stdin)
ids = [i['id'] for i in body['items']]
assert '$DOC_ID' not in ids, f'substring tag match found — expected no match'
print('PASS: no substring tag collision')
"

echo "S62 smoke test PASSED"
