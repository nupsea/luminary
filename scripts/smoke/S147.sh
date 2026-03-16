#!/usr/bin/env bash
# Smoke test for S147: SelectionActionBar -- POST /annotations endpoint.
set -euo pipefail
BASE="http://localhost:7820"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. GET /documents to find a document for annotation test
DOCS=$(curl -s "${BASE}/documents?sort=newest&page=1&page_size=1")
DOC_COUNT=$(echo "${DOCS}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('items',[])))" 2>/dev/null || echo "0")
if [ "${DOC_COUNT}" = "0" ]; then
  echo "SKIP: no documents ingested -- cannot test POST /annotations"
  exit 0
fi

DOC_ID=$(echo "${DOCS}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['items'][0]['id'])" 2>/dev/null)

# 3. GET /documents/{id} to find first section_id (required by annotations endpoint)
DOC_DETAIL=$(curl -s "${BASE}/documents/${DOC_ID}")
SECTION_ID=$(echo "${DOC_DETAIL}" | python3 -c "import sys,json; d=json.load(sys.stdin); secs=d.get('sections',[]); print(secs[0]['id'] if secs else '')" 2>/dev/null || echo "")

if [ -z "${SECTION_ID}" ]; then
  echo "SKIP: document has no sections -- cannot test POST /annotations"
  exit 0
fi

# 4. POST /annotations should accept a highlight payload
HTTP_ANN=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -d "{\"document_id\":\"${DOC_ID}\",\"section_id\":\"${SECTION_ID}\",\"chunk_id\":null,\"selected_text\":\"smoke test\",\"start_offset\":0,\"end_offset\":10,\"color\":\"yellow\",\"note_text\":null}" \
  "${BASE}/annotations")
if [ "$HTTP_ANN" != "200" ] && [ "$HTTP_ANN" != "201" ]; then
  echo "FAIL: POST /annotations returned ${HTTP_ANN}"
  exit 1
fi

echo "PASS: S147 -- POST /annotations endpoint responds correctly"
