#!/usr/bin/env bash
# Smoke test for S194 -- References: URL validation and pruning of dead links
set -euo pipefail

BASE="http://localhost:7820"
FAIL=0

echo "=== S194 Smoke: Reference URL validation ==="

# Find an existing document
echo "[1/5] Finding an existing document..."
TMPFILE=$(mktemp /tmp/s194_1_XXXXXX.json)
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
pick=docs[0] if docs else None
print(pick['id'] if pick else '')
" 2>/dev/null || true)
if [ -z "$DOC_ID" ]; then
  echo "  SKIP: no documents in library"
  exit 0
fi
echo "  OK: doc_id=$DOC_ID"

# GET /references/documents/{id} -- default (exclude invalid)
echo "[2/5] GET /references/documents/{id} (default)..."
TMPFILE=$(mktemp /tmp/s194_2_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/references/documents/$DOC_ID")
BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"
if [ "$STATUS" != "200" ]; then
  echo "  FAIL: expected 200, got $STATUS"
  FAIL=1
else
  HAS_DOC_ID=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('document_id',''))")
  if [ "$HAS_DOC_ID" = "$DOC_ID" ]; then
    echo "  OK: document_id present in response"
  else
    echo "  FAIL: document_id missing or wrong"
    FAIL=1
  fi
fi

# GET /references/documents/{id}?include_invalid=true
echo "[3/5] GET /references/documents/{id}?include_invalid=true..."
TMPFILE=$(mktemp /tmp/s194_3_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/references/documents/$DOC_ID?include_invalid=true")
rm -f "$TMPFILE"
if [ "$STATUS" != "200" ]; then
  echo "  FAIL: expected 200, got $STATUS"
  FAIL=1
else
  echo "  OK: include_invalid=true accepted"
fi

# POST /references/documents/{id}/validate
echo "[4/5] POST /references/documents/{id}/validate..."
TMPFILE=$(mktemp /tmp/s194_4_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X POST "$BASE/references/documents/$DOC_ID/validate")
BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"
if [ "$STATUS" != "200" ]; then
  echo "  FAIL: expected 200, got $STATUS"
  FAIL=1
else
  HAS_VALID=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print('valid' in d and 'invalid' in d)")
  if [ "$HAS_VALID" = "True" ]; then
    echo "  OK: valid/invalid counts in response"
  else
    echo "  FAIL: missing valid/invalid in response"
    FAIL=1
  fi
fi

# POST /references/documents/{id}/refresh
echo "[5/5] POST /references/documents/{id}/refresh..."
TMPFILE=$(mktemp /tmp/s194_5_XXXXXX.json)
STATUS=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X POST "$BASE/references/documents/$DOC_ID/refresh")
BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"
if [ "$STATUS" != "202" ]; then
  echo "  FAIL: expected 202, got $STATUS"
  FAIL=1
else
  HAS_EXTRACTED=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print('extracted' in d)")
  if [ "$HAS_EXTRACTED" = "True" ]; then
    echo "  OK: extracted count in response"
  else
    echo "  FAIL: missing extracted in response"
    FAIL=1
  fi
fi

if [ "$FAIL" -ne 0 ]; then
  echo "=== S194 SMOKE FAILED ==="
  exit 1
fi
echo "=== S194 SMOKE PASSED ==="
exit 0
