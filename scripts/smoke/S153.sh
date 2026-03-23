#!/usr/bin/env bash
# Smoke test for S153: Bloom's taxonomy coverage audit endpoint
set -euo pipefail
BASE="http://localhost:7820"

# Get first document ID from the library
DOC_ID=$(curl -sf "${BASE}/documents" | python3 -c "
import sys, json
docs = json.load(sys.stdin).get('items', [])
print(docs[0]['id'] if docs else '')
")

if [ -z "$DOC_ID" ]; then
  echo "SKIP: no documents in DB -- ingest a document first"
  exit 0
fi

# GET /flashcards/audit/{document_id} -- must return 200 with CoverageReport fields
RESP=$(curl -sf "${BASE}/flashcards/audit/${DOC_ID}")

echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'total_cards' in d, f'Missing total_cards: {d}'
assert 'coverage_score' in d, f'Missing coverage_score: {d}'
assert 'gaps' in d, f'Missing gaps: {d}'
assert 'by_bloom_level' in d, f'Missing by_bloom_level: {d}'
assert 'by_section' in d, f'Missing by_section: {d}'
print(f'  total_cards={d[\"total_cards\"]}, coverage_score={d[\"coverage_score\"]:.2f}, gaps={len(d[\"gaps\"])}')
"

echo "PASS: S153 smoke test passed"
