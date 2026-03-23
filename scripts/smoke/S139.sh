#!/usr/bin/env bash
# Smoke test for S139: Prerequisites and FSRS-aware study path
# Tests GET /study/start and GET /study/path endpoints
set -euo pipefail
BASE="http://localhost:7820"

# Fetch first document ID
DOCS=$(curl -sf "$BASE/documents?page_size=1" | python3 -c "
import sys, json
d = json.load(sys.stdin)
items = d.get('items', [])
print(items[0]['id'] if items else '')
")

if [ -z "$DOCS" ]; then
  echo "SKIP: no documents ingested"
  exit 0
fi

DOC_ID="$DOCS"

# Test GET /study/start
RESP=$(curl -sf "$BASE/study/start?document_id=${DOC_ID}")
echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'concepts' in d, f'missing concepts key: {d}'
assert 'document_id' in d, f'missing document_id key: {d}'
print(f'  concepts returned: {len(d[\"concepts\"])}')
"
echo "PASS: GET /study/start?document_id=$DOC_ID"

# Test GET /study/path if start concepts are available
CONCEPT=$(echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
concepts = d.get('concepts', [])
print(concepts[0]['concept'] if concepts else '')
" 2>/dev/null || echo "")

if [ -n "$CONCEPT" ]; then
  ENCODED=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1]))" "$CONCEPT")
  curl -sf "$BASE/study/path?document_id=${DOC_ID}&concept=${ENCODED}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'path' in d, f'missing path key: {d}'
assert 'concept' in d, f'missing concept key: {d}'
assert 'document_id' in d, f'missing document_id key: {d}'
"
  echo "PASS: GET /study/path?document_id=$DOC_ID&concept=$CONCEPT"
else
  echo "SKIP: no entry-point concepts for doc=$DOC_ID (no prerequisites extracted yet)"
fi
