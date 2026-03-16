#!/usr/bin/env bash
set -euo pipefail
DOC_ID="${1:-}"
if [ -z "$DOC_ID" ]; then
  echo "Usage: $0 <document_id>"
  exit 1
fi

IMAGES_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:7820/documents/${DOC_ID}/images")
if [ "$IMAGES_STATUS" -ne 200 ]; then
  echo "FAIL: GET /documents/${DOC_ID}/images returned $IMAGES_STATUS"
  exit 1
fi

ENRICHMENT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:7820/documents/${DOC_ID}/enrichment")
if [ "$ENRICHMENT_STATUS" -ne 200 ]; then
  echo "FAIL: GET /documents/${DOC_ID}/enrichment returned $ENRICHMENT_STATUS"
  exit 1
fi

echo "PASS: S133 endpoints returned 200 for doc ${DOC_ID}"
