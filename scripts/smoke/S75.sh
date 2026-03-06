#!/usr/bin/env bash
# Smoke test for S75: SectionSummaryModel + section summarization node.
# (1) POST /ingest with a small TXT fixture, poll for stage=complete.
# (2) GET /summarize/{id}/sections returns HTTP 200 and a JSON array.
# Requires the backend to be running on localhost:8000.

set -euo pipefail

BASE="http://localhost:8000"
FIXTURE="backend/tests/fixtures/art_of_unix_ch1.txt"

if [ ! -f "$FIXTURE" ]; then
  echo "FAIL: fixture not found at $FIXTURE"
  exit 1
fi

# POST /ingest
echo "Ingesting fixture..."
INGEST_RESP=$(curl -s -X POST "${BASE}/ingest" \
  -F "file=@${FIXTURE};type=text/plain" \
  -F "content_type=notes")

DOC_ID=$(echo "$INGEST_RESP" | python3 -c "import sys, json; print(json.load(sys.stdin)['document_id'])" 2>/dev/null || echo "")

if [ -z "$DOC_ID" ]; then
  echo "FAIL: could not parse document_id from ingest response: $INGEST_RESP"
  exit 1
fi
echo "Document ID: $DOC_ID"

# Poll GET /documents/{id} until stage=complete or timeout
MAX_WAIT=120
ELAPSED=0
STAGE=""
while [ "$STAGE" != "complete" ] && [ "$ELAPSED" -lt "$MAX_WAIT" ]; do
  sleep 5
  ELAPSED=$((ELAPSED + 5))
  STAGE=$(curl -s "${BASE}/documents/${DOC_ID}" | python3 -c "import sys, json; print(json.load(sys.stdin).get('stage', ''))" 2>/dev/null || echo "")
  echo "  stage=${STAGE} (${ELAPSED}s)"
done

if [ "$STAGE" != "complete" ]; then
  echo "FAIL: document did not reach stage=complete within ${MAX_WAIT}s (last stage: ${STAGE})"
  exit 1
fi

# GET /summarize/{id}/sections — must be HTTP 200 with a JSON array
HTTP_CODE=$(curl -s -o /tmp/s75_sections.json -w "%{http_code}" \
  "${BASE}/summarize/${DOC_ID}/sections")

if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: GET /summarize/${DOC_ID}/sections returned ${HTTP_CODE} (expected 200)"
  exit 1
fi

# Verify response is a JSON array (may be empty for very small docs)
IS_ARRAY=$(python3 -c "import json; data=json.load(open('/tmp/s75_sections.json')); print('yes' if isinstance(data, list) else 'no')" 2>/dev/null || echo "no")
if [ "$IS_ARRAY" != "yes" ]; then
  echo "FAIL: GET /summarize/${DOC_ID}/sections did not return a JSON array"
  cat /tmp/s75_sections.json
  exit 1
fi

COUNT=$(python3 -c "import json; print(len(json.load(open('/tmp/s75_sections.json'))))" 2>/dev/null || echo "0")
echo "PASS: GET /summarize/${DOC_ID}/sections returned HTTP 200 with JSON array (${COUNT} items)"
