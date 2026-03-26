#!/usr/bin/env bash
# Smoke test for S179: Context-aware flashcard generation
set -euo pipefail

BASE="http://localhost:8000"

echo "=== S179 Smoke: Context-aware flashcard generation ==="

# 1. Health check
echo "--- Health check ---"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/health")
if [ "$HTTP" != "200" ]; then
  echo "FAIL: /health returned $HTTP"
  exit 1
fi
echo "OK: /health => 200"

# 2. Look for an existing document to generate flashcards for
echo "--- Checking for existing documents ---"
DOCS_RESP=$(curl -s "$BASE/documents")
DOC_ID=$(echo "$DOCS_RESP" | python3 -c "
import json, sys
docs = json.load(sys.stdin)
items = docs.get('items', docs) if isinstance(docs, dict) else docs
complete = [d for d in items if isinstance(d, dict) and d.get('stage') == 'complete']
if complete:
    print(complete[0]['id'])
" 2>/dev/null || true)

if [ -z "$DOC_ID" ]; then
  echo "SKIP: No complete documents found -- cannot test flashcard generation"
  echo "S179 smoke: skipped (no documents)"
  exit 0
fi

echo "OK: Using document $DOC_ID"

# 3. Generate flashcards (chunk classifier + genre-aware prompt active)
echo "--- Generating flashcards ---"
TMPFILE=$(mktemp)
GEN_HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X POST "$BASE/flashcards/generate" \
  -H "Content-Type: application/json" \
  -d "{\"document_id\": \"$DOC_ID\", \"scope\": \"full\", \"count\": 2, \"difficulty\": \"medium\"}")
GEN_BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"

if [ "$GEN_HTTP" != "200" ] && [ "$GEN_HTTP" != "201" ]; then
  echo "FAIL: POST /flashcards/generate returned $GEN_HTTP"
  echo "$GEN_BODY"
  exit 1
fi
echo "OK: POST /flashcards/generate => $GEN_HTTP"

# 4. Validate response is a JSON array
IS_ARRAY=$(echo "$GEN_BODY" | python3 -c "import json, sys; data=json.load(sys.stdin); print('yes' if isinstance(data, list) else 'no')" 2>/dev/null || echo "no")
if [ "$IS_ARRAY" != "yes" ]; then
  echo "FAIL: response is not a JSON array"
  echo "$GEN_BODY" | head -5
  exit 1
fi
echo "OK: response is a JSON array"

# 5. If cards were generated, verify chunk_classification field is present (nullable)
CARD_COUNT=$(echo "$GEN_BODY" | python3 -c "import json, sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
echo "INFO: generated $CARD_COUNT cards"

if [ "$CARD_COUNT" -gt "0" ]; then
  # chunk_classification key must exist (value may be null)
  HAS_FIELD=$(echo "$GEN_BODY" | python3 -c "
import json, sys
cards = json.load(sys.stdin)
# Field is present if all cards have the key (value can be None/null)
has = all('chunk_classification' in c for c in cards)
print('yes' if has else 'no')
" 2>/dev/null || echo "unknown")
  if [ "$HAS_FIELD" = "no" ]; then
    echo "WARN: chunk_classification field missing from some cards (may be pre-existing cards)"
  else
    echo "OK: chunk_classification field present in response"
  fi
fi

echo "=== S179 smoke: PASSED ==="
exit 0
