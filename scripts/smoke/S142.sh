#!/usr/bin/env bash
# Smoke test for S142: web-grounded chat
# Verifies GET /settings/web-search and POST /qa with web_enabled=false both work.
set -euo pipefail

BASE="http://localhost:7820"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. GET /settings/web-search must return 200 with provider and enabled fields
RESULT=$(mktemp)
HTTP=$(curl -s -o "${RESULT}" -w "%{http_code}" "${BASE}/settings/web-search")
if [ "$HTTP" != "200" ]; then
  echo "FAIL: GET /settings/web-search returned ${HTTP}"
  cat "${RESULT}"
  rm -f "${RESULT}"
  exit 1
fi
HAS_PROVIDER=$(python3 -c "import json,sys; d=json.load(sys.stdin); print('yes' if 'provider' in d and 'enabled' in d else 'no')" < "${RESULT}")
rm -f "${RESULT}"
if [ "${HAS_PROVIDER}" != "yes" ]; then
  echo "FAIL: /settings/web-search missing 'provider' or 'enabled' field"
  exit 1
fi

# 3. POST /qa with web_enabled=false must return 200 and a done SSE event
TMPFILE=$(mktemp)
HTTP=$(curl -s -o "${TMPFILE}" -w "%{http_code}" \
  -X POST "${BASE}/qa" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is asyncio?", "scope": "all", "web_enabled": false}')

if [ "$HTTP" != "200" ]; then
  echo "FAIL: POST /qa returned ${HTTP}"
  cat "${TMPFILE}"
  rm -f "${TMPFILE}"
  exit 1
fi

HAS_DONE=$(grep -c '"done":true' "${TMPFILE}" || true)
rm -f "${TMPFILE}"

if [ "${HAS_DONE}" -lt 1 ]; then
  echo "FAIL: SSE stream missing done event"
  exit 1
fi

echo "PASS: S142 smoke test -- GET /settings/web-search and POST /qa with web_enabled=false both pass"
