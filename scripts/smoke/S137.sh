#!/usr/bin/env bash
# Smoke test for S137: POST /flashcards/generate-technical returns HTTP 201
# with a JSON array where at least one card has flashcard_type set.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. Upload a small tech document so we have something to generate from
DOC_TMPFILE=$(mktemp /tmp/s137doc.XXXXXX.txt)
cat > "${DOC_TMPFILE}" << 'DOCEOF'
# Python Functions

def add(a, b):
    return a + b

## List vs Tuple trade-off

Lists are mutable; tuples are immutable.
Use tuples for fixed data, lists when you need append/remove.

WARNING: Never modify a list while iterating over it.
DOCEOF

UPLOAD_TMPFILE=$(mktemp)
HTTP_UPLOAD=$(curl -s -o "${UPLOAD_TMPFILE}" -w "%{http_code}" \
  -X POST "${BASE}/documents/upload" \
  -F "file=@${DOC_TMPFILE};type=text/plain" \
  -F "content_type=tech_book")

rm -f "${DOC_TMPFILE}"

if [ "$HTTP_UPLOAD" != "200" ] && [ "$HTTP_UPLOAD" != "201" ]; then
  echo "FAIL: document upload got ${HTTP_UPLOAD}"
  cat "${UPLOAD_TMPFILE}"
  rm -f "${UPLOAD_TMPFILE}"
  exit 1
fi

DOC_ID=$(python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" < "${UPLOAD_TMPFILE}")
rm -f "${UPLOAD_TMPFILE}"

if [ -z "${DOC_ID}" ]; then
  echo "FAIL: could not extract document id from upload response"
  exit 1
fi

echo "Uploaded document id=${DOC_ID}, waiting 3s for ingestion..."
sleep 3

# 3. POST /flashcards/generate-technical
RESULT_TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -s -o "${RESULT_TMPFILE}" -w "%{http_code}" \
  -X POST "${BASE}/flashcards/generate-technical" \
  -H "Content-Type: application/json" \
  -d "{\"document_id\": \"${DOC_ID}\", \"scope\": \"full\", \"count\": 3}")

if [ "$HTTP_STATUS" != "201" ]; then
  echo "FAIL: expected 201, got ${HTTP_STATUS}"
  cat "${RESULT_TMPFILE}"
  rm -f "${RESULT_TMPFILE}"
  exit 1
fi

BODY=$(cat "${RESULT_TMPFILE}")
rm -f "${RESULT_TMPFILE}"

# Body must be a non-empty JSON array
if [[ "$BODY" != \[* ]]; then
  echo "FAIL: expected JSON array body, got: ${BODY:0:120}"
  exit 1
fi

CARD_COUNT=$(python3 -c "import json,sys; print(len(json.loads(sys.stdin.read())))" <<< "${BODY}")
if [ "${CARD_COUNT}" -lt 1 ]; then
  echo "FAIL: expected at least one card, got ${CARD_COUNT}"
  exit 1
fi

# At least one card must have flashcard_type set (not null)
HAS_TYPE=$(python3 -c "
import json, sys
cards = json.loads(sys.stdin.read())
has_type = any(c.get('flashcard_type') is not None for c in cards)
print('yes' if has_type else 'no')
" <<< "${BODY}")

if [ "${HAS_TYPE}" != "yes" ]; then
  echo "FAIL: no card has flashcard_type set. Cards: ${BODY:0:200}"
  exit 1
fi

echo "PASS: S137 -- POST /flashcards/generate-technical returned HTTP 201 with ${CARD_COUNT} typed cards"
