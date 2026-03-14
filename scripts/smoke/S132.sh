#!/usr/bin/env bash
# S132 smoke test: GET /documents/{doc_id}/objectives returns 2xx
set -euo pipefail

DOC_ID="${1:-}"
if [ -z "$DOC_ID" ]; then
  echo "Usage: $0 <document_id>"
  exit 1
fi

STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/documents/${DOC_ID}/objectives")
if [ "$STATUS" -ne 200 ]; then
  echo "FAIL: GET /documents/${DOC_ID}/objectives returned $STATUS"
  exit 1
fi
echo "PASS: GET /documents/${DOC_ID}/objectives returned 200"
