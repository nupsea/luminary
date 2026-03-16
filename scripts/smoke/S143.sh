#!/usr/bin/env bash
# Smoke test for S143: learning objectives tracking.
# Verifies GET /documents/{id}/progress returns 200 with expected schema.
set -euo pipefail

BASE="http://localhost:7820"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. Find the most-recently ingested document
TMPFILE=$(mktemp)
HTTP=$(curl -s -o "${TMPFILE}" -w "%{http_code}" "${BASE}/documents?sort=newest&page_size=1")
if [ "$HTTP" != "200" ]; then
  echo "FAIL: GET /documents returned ${HTTP}"
  cat "${TMPFILE}"
  rm -f "${TMPFILE}"
  exit 1
fi

DOC_ID=$(python3 -c "
import json, sys
d = json.load(sys.stdin)
items = d.get('items', [])
print(items[0]['id'] if items else '')
" < "${TMPFILE}")
rm -f "${TMPFILE}"

if [ -z "$DOC_ID" ]; then
  echo "SKIP: no documents ingested yet"
  exit 0
fi

# 3. GET /documents/{id}/progress must return 200 with required fields
RESULT=$(mktemp)
HTTP=$(curl -s -o "${RESULT}" -w "%{http_code}" "${BASE}/documents/${DOC_ID}/progress")
if [ "$HTTP" != "200" ]; then
  echo "FAIL: GET /documents/${DOC_ID}/progress returned ${HTTP}"
  cat "${RESULT}"
  rm -f "${RESULT}"
  exit 1
fi

HAS_FIELDS=$(python3 -c "
import json, sys
d = json.load(sys.stdin)
required = {'document_id', 'total_objectives', 'covered_objectives', 'progress_pct', 'by_chapter'}
missing = required - set(d.keys())
print('missing:' + ','.join(missing) if missing else 'ok')
" < "${RESULT}")
rm -f "${RESULT}"

if [ "${HAS_FIELDS}" != "ok" ]; then
  echo "FAIL: response missing fields: ${HAS_FIELDS}"
  exit 1
fi

echo "PASS: S143 smoke test -- GET /documents/${DOC_ID}/progress returns correct schema"
