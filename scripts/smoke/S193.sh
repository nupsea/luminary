#!/usr/bin/env bash
# Smoke test for S193 -- Glossary: persistent storage, categorization, and regeneration
set -euo pipefail

BASE="http://localhost:7820"
FAIL=0

echo "=== S193 Smoke: Glossary persistence endpoints ==="

# Find an existing document to test with
echo "[1/5] Finding an existing document..."
TMPFILE=$(mktemp /tmp/s193_1_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/documents?limit=1")
BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"
if [ "$STATUS" != "200" ]; then
  echo "  FAIL: cannot list documents ($STATUS)"
  exit 1
fi
DOC_ID=$(echo "$BODY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
docs=data.get('items',data) if isinstance(data,dict) else data
# Prefer book docs for glossary extraction
books=[d for d in docs if d.get('content_type')=='book']
pick=books[0] if books else (docs[0] if docs else None)
print(pick['id'] if pick else '')
" 2>/dev/null || true)
if [ -z "$DOC_ID" ]; then
  echo "  SKIP: no documents in library"
  exit 0
fi
echo "  Found document: $DOC_ID"

# Step 2: GET /explain/glossary/{doc_id}/cached -> 200 (may be empty list)
echo "[2/5] GET /explain/glossary/{doc_id}/cached -> 200"
TMPFILE=$(mktemp /tmp/s193_2_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/explain/glossary/$DOC_ID/cached")
BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"
if [ "$STATUS" = "200" ]; then
  echo "  PASS: cached endpoint returns 200"
else
  echo "  FAIL: expected 200, got $STATUS"
  FAIL=1
fi

# Step 3: POST /explain/glossary/{doc_id} -> 200 (generate + persist)
echo "[3/5] POST /explain/glossary/{doc_id} -> 200"
TMPFILE=$(mktemp /tmp/s193_3_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X POST "$BASE/explain/glossary/$DOC_ID")
BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"
if [ "$STATUS" = "200" ]; then
  echo "  PASS: glossary generated"
  # Extract first term ID for DELETE test
  TERM_ID=$(echo "$BODY" | python3 -c "import sys,json; terms=json.load(sys.stdin); print(terms[0]['id'] if terms else '')" 2>/dev/null || true)
  TERM_COUNT=$(echo "$BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
  echo "  Terms generated: $TERM_COUNT"
elif [ "$STATUS" = "503" ]; then
  echo "  SKIP: Ollama unavailable (503) -- expected if Ollama is not running"
  echo "=== S193 SMOKE PASSED (partial -- Ollama offline) ==="
  exit 0
else
  echo "  FAIL: expected 200 or 503, got $STATUS"
  echo "  Body: $BODY"
  FAIL=1
fi

# Step 4: GET /explain/glossary/{doc_id}/cached -> 200 with terms
echo "[4/5] GET /explain/glossary/{doc_id}/cached -> 200 (with terms)"
TMPFILE=$(mktemp /tmp/s193_4_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/explain/glossary/$DOC_ID/cached")
BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"
if [ "$STATUS" = "200" ]; then
  CACHED_COUNT=$(echo "$BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
  if [ "$CACHED_COUNT" -gt 0 ]; then
    echo "  PASS: cached terms returned ($CACHED_COUNT terms)"
  else
    echo "  FAIL: cached endpoint returned empty after generation"
    FAIL=1
  fi
else
  echo "  FAIL: expected 200, got $STATUS"
  FAIL=1
fi

# Step 5: DELETE /explain/glossary/{doc_id}/terms/{term_id} -> 204
if [ -n "${TERM_ID:-}" ]; then
  echo "[5/5] DELETE /explain/glossary/{doc_id}/terms/{term_id} -> 204"
  TMPFILE=$(mktemp /tmp/s193_5_XXXXXX.json)
  STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X DELETE "$BASE/explain/glossary/$DOC_ID/terms/$TERM_ID")
  rm -f "$TMPFILE"
  if [ "$STATUS" = "204" ]; then
    echo "  PASS: term deleted"
  else
    echo "  FAIL: expected 204, got $STATUS"
    FAIL=1
  fi
else
  echo "[5/5] SKIP: no term ID available for DELETE test"
fi

if [ "$FAIL" -ne 0 ]; then
  echo "=== S193 SMOKE FAILED ==="
  exit 1
fi

echo "=== S193 SMOKE PASSED ==="
exit 0
