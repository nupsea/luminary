#!/usr/bin/env bash
# Smoke test for S152: Reading position persistence
# Requires a running backend at localhost:7820 with at least one ingested document.

set -euo pipefail

BASE="http://localhost:7820"

# --- Step 1: Get the first document ID ---
DOCS=$(curl -sf "${BASE}/documents" | python3 -c "import sys,json; docs=json.load(sys.stdin).get('items',[]); print(docs[0]['id'] if docs else '')")
if [ -z "$DOCS" ]; then
  echo "SKIP: no documents in DB -- ingest a document first"
  exit 0
fi
DOC_ID="$DOCS"

# --- Step 2: GET position should 404 initially (if no position saved yet) ---
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/documents/${DOC_ID}/position")
if [ "$STATUS" != "200" ] && [ "$STATUS" != "404" ]; then
  echo "FAIL: GET /documents/${DOC_ID}/position returned unexpected status ${STATUS}"
  exit 1
fi

# --- Step 3: POST a reading position ---
RESP=$(curl -sf -X POST \
  -H "Content-Type: application/json" \
  -d '{"last_section_id":"smoke-sec-1","last_section_heading":"Smoke Test Section","last_pdf_page":7}' \
  "${BASE}/documents/${DOC_ID}/position")
echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('last_pdf_page')==7, f'Expected page 7, got {d}'"

# --- Step 4: GET the position back ---
RESP2=$(curl -sf "${BASE}/documents/${DOC_ID}/position")
echo "$RESP2" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('last_section_heading')=='Smoke Test Section', f'Expected heading, got {d}'; assert d.get('last_pdf_page')==7, f'Expected page, got {d}'"

# --- Step 5: POST again (upsert) with a different page ---
RESP3=$(curl -sf -X POST \
  -H "Content-Type: application/json" \
  -d '{"last_section_id":"smoke-sec-2","last_section_heading":"Chapter 2","last_pdf_page":42}' \
  "${BASE}/documents/${DOC_ID}/position")
echo "$RESP3" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('last_pdf_page')==42, f'Expected page 42, got {d}'"

echo "PASS: S152 smoke test passed"
