#!/usr/bin/env bash
# Smoke test for S138: GET /references/documents/{id} returns HTTP 200 with references key.
# Requires a running backend at http://localhost:7820.
set -euo pipefail

BASE="http://localhost:7820"

# Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# Upload a minimal tech document
DOC_TMPFILE=$(mktemp /tmp/s138doc.XXXXXX.txt)
cat > "${DOC_TMPFILE}" << 'DOCEOF'
## Python Generators

A generator is a lazy iterator. The yield keyword pauses execution.
Use itertools.islice to take N items from an infinite generator.
DOCEOF

UPLOAD_TMPFILE=$(mktemp)
HTTP_UPLOAD=$(curl -s -o "${UPLOAD_TMPFILE}" -w "%{http_code}" \
  -X POST "${BASE}/documents/ingest" \
  -F "file=@${DOC_TMPFILE};type=text/plain" \
  -F "content_type=tech_book")
rm -f "${DOC_TMPFILE}"

if [ "$HTTP_UPLOAD" != "200" ] && [ "$HTTP_UPLOAD" != "201" ]; then
  echo "FAIL: document upload got ${HTTP_UPLOAD}"
  cat "${UPLOAD_TMPFILE}"
  rm -f "${UPLOAD_TMPFILE}"
  exit 1
fi

DOC_ID=$(python3 -c "import json,sys; print(json.load(sys.stdin)['document_id'])" < "${UPLOAD_TMPFILE}")
rm -f "${UPLOAD_TMPFILE}"

if [ -z "${DOC_ID}" ]; then
  echo "FAIL: could not extract document id from the ingest response"
  exit 1
fi

# Delete the document however this script exits -- see S137.
cleanup_doc() { curl -s -o /dev/null -X DELETE "${BASE}/documents/${DOC_ID}" || true; }
trap cleanup_doc EXIT

# Ingestion is asynchronous; poll the stage rather than guessing at a sleep.
echo "Ingested doc=${DOC_ID}, waiting for stage=complete..."
for _ in $(seq 1 60); do
  STAGE=$(curl -s "${BASE}/documents/${DOC_ID}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('stage',''))" 2>/dev/null || echo "")
  [ "$STAGE" = "complete" ] && break
  sleep 2
done
if [ "$STAGE" != "complete" ]; then
  echo "FAIL: document did not reach stage=complete (last stage: ${STAGE:-unknown})"
  exit 1
fi

# GET /references/documents/{id} -- must return 200 with references key
RESULT_TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -s -o "${RESULT_TMPFILE}" -w "%{http_code}" \
  "${BASE}/references/documents/${DOC_ID}")

if [ "$HTTP_STATUS" != "200" ]; then
  echo "FAIL: expected 200, got ${HTTP_STATUS}"
  cat "${RESULT_TMPFILE}"
  rm -f "${RESULT_TMPFILE}"
  exit 1
fi

HAS_KEY=$(python3 -c "
import json, sys
body = json.load(sys.stdin)
print('yes' if 'references' in body else 'no')
" < "${RESULT_TMPFILE}")

rm -f "${RESULT_TMPFILE}"

if [ "${HAS_KEY}" != "yes" ]; then
  echo "FAIL: response missing 'references' key"
  exit 1
fi

echo "PASS: S138 -- GET /references/documents/${DOC_ID} returned HTTP 200 with references key"
