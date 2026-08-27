#!/usr/bin/env bash
# S110 smoke: reading progress upsert and reading_progress_pct in document detail
set -euo pipefail

BASE="http://localhost:7820"

echo "S110 [1/4]: Find a document in the library..."
DOC_ID=$(curl -sf "${BASE}/documents?page_size=1" | python3 -c "
import sys, json
docs = json.load(sys.stdin)['items']
print(docs[0]['id']) if docs else print('')
" 2>/dev/null || true)

if [ -z "$DOC_ID" ]; then
  echo "SKIP: No documents in library -- ingest a document first"
  exit 0
fi
echo "Using document: ${DOC_ID}"

# Unique per run. A fixed section id made this script pass once and fail on every
# later run against the same database -- the upsert had already counted the first
# visit, so "first visit -> view_count=1" read 3 and reported a product failure
# that was the script's own leftover state. A fresh id measures the increment
# itself, which is what the script is named for.
SECTION_ID="smoke-section-s110-$(date +%s)-$$"

echo "S110 [2/4]: POST /reading/progress (first visit) -> view_count=1..."
RESP=$(curl -sf -X POST "${BASE}/reading/progress" \
  -H "Content-Type: application/json" \
  -d "{\"document_id\":\"${DOC_ID}\",\"section_id\":\"${SECTION_ID}\"}")
echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['view_count'] == 1, f'Expected 1, got {d[\"view_count\"]}'
" || { echo "FAIL: view_count not 1"; exit 1; }
echo "PASS: first POST returns view_count=1"

echo "S110 [3/4]: POST /reading/progress (second visit) -> view_count=2..."
RESP2=$(curl -sf -X POST "${BASE}/reading/progress" \
  -H "Content-Type: application/json" \
  -d "{\"document_id\":\"${DOC_ID}\",\"section_id\":\"${SECTION_ID}\"}")
echo "$RESP2" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['view_count'] == 2, f'Expected 2, got {d[\"view_count\"]}'
" || { echo "FAIL: view_count not 2"; exit 1; }
echo "PASS: second POST returns view_count=2"

echo "S110 [4/4]: GET /documents/{id} includes reading_progress_pct..."
DOC=$(curl -sf "${BASE}/documents/${DOC_ID}")
echo "$DOC" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'reading_progress_pct' in d, 'missing reading_progress_pct field'
assert isinstance(d['reading_progress_pct'], float), 'reading_progress_pct must be float'
" || { echo "FAIL: reading_progress_pct missing or wrong type"; exit 1; }
echo "PASS: reading_progress_pct present in document detail"

echo "S110: ALL CHECKS PASSED"
