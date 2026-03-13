#!/usr/bin/env bash
# S112 smoke: graph-flashcard entity-pairs preview and generate-from-graph endpoint
set -euo pipefail

BASE="http://localhost:8000"

echo "S112 [1/3]: Find first ingested document..."
DOC_ID=$(curl -sf "${BASE}/documents?sort=newest&page=1&page_size=1" | python3 -c "
import sys, json
d = json.load(sys.stdin)
items = d.get('items', [])
print(items[0]['id'] if items else '')
" 2>/dev/null || echo "")

if [ -z "$DOC_ID" ]; then
  echo "SKIP: no documents ingested; cannot verify entity-pairs or generate-from-graph"
  exit 0
fi

echo "S112 [2/3]: GET /flashcards/entity-pairs -- must return 200 with pairs key..."
PAIRS_RESP=$(curl -sf "${BASE}/flashcards/entity-pairs?document_id=${DOC_ID}")
echo "$PAIRS_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'pairs' in d, f'missing pairs key, got: {d}'
print(f'  {len(d[\"pairs\"])} pair(s) found')
" || { echo "FAIL: entity-pairs response malformed"; exit 1; }
echo "PASS"

echo "S112 [3/3]: POST /flashcards/generate-from-graph -- must return 201 or 503..."
STATUS=$(curl -sf -o /dev/null -w "%{http_code}" -X POST \
  "${BASE}/flashcards/generate-from-graph" \
  -H "Content-Type: application/json" \
  -d "{\"document_id\": \"${DOC_ID}\", \"k\": 3}" 2>/dev/null || echo "000")
if [ "$STATUS" = "201" ]; then
  echo "PASS: generate-from-graph returned 201"
elif [ "$STATUS" = "503" ]; then
  echo "PASS (degraded): generate-from-graph returned 503 -- Ollama not running"
else
  echo "FAIL: unexpected status ${STATUS}"; exit 1
fi

echo "S112: ALL CHECKS PASSED"
