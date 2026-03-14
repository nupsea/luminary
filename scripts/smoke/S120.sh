#!/usr/bin/env bash
set -e
BASE=http://localhost:8000

# 1. GET /documents/{unknown}/audio returns 404
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/documents/00000000-0000-0000-0000-000000000000/audio")
[ "${STATUS}" = "404" ] || { echo "FAIL: expected 404 for unknown doc audio, got ${STATUS}"; exit 1; }

# 2. Library endpoint still returns expected shape after S120 changes
RESP=$(curl -sf "${BASE}/documents")
echo "${RESP}" | grep -q '"items"' || { echo "FAIL: /documents did not return items"; exit 1; }

# 3. DocumentDetail includes audio_duration_seconds field (may be null)
# Pick the first document from the list (skip if library is empty)
FIRST_ID=$(echo "${RESP}" | python3 -c "import sys,json; items=json.load(sys.stdin)['items']; print(items[0]['id'] if items else '')" 2>/dev/null || true)
if [ -n "${FIRST_ID}" ]; then
    DETAIL=$(curl -sf "${BASE}/documents/${FIRST_ID}")
    echo "${DETAIL}" | grep -q '"audio_duration_seconds"' || { echo "FAIL: DocumentDetail missing audio_duration_seconds"; exit 1; }
fi

echo "S120 smoke: PASS"
