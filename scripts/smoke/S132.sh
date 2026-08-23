#!/usr/bin/env bash
# S132 smoke test: GET /documents/{doc_id}/objectives returns 2xx
set -euo pipefail

BASE="${BASE:-http://localhost:7820}"

# `all.sh` passes no arguments, so requiring one made this script a guaranteed
# failure in the suite it belongs to. The id is still accepted as an override;
# otherwise pick a complete document, and skip cleanly when the library has none.
DOC_ID="${1:-}"
if [ -z "$DOC_ID" ]; then
  DOC_ID=$(curl -s "${BASE}/documents" | python3 -c "
import json, sys
docs = json.load(sys.stdin)
items = docs.get('items', docs) if isinstance(docs, dict) else docs
ready = [d for d in items if isinstance(d, dict) and d.get('stage') == 'complete']
print(ready[0]['id'] if ready else '')
" 2>/dev/null || echo "")
fi
if [ -z "$DOC_ID" ]; then
  echo "SKIP: no complete document in the library"
  exit 0
fi

STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:7820/documents/${DOC_ID}/objectives")
if [ "$STATUS" -ne 200 ]; then
  echo "FAIL: GET /documents/${DOC_ID}/objectives returned $STATUS"
  exit 1
fi
echo "PASS: GET /documents/${DOC_ID}/objectives returned 200"
