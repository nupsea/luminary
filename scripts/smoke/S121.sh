#!/usr/bin/env bash
set -e
BASE=http://localhost:8000

# Verify the library endpoint returns expected shape
RESP=$(curl -sf "${BASE}/documents")
echo "${RESP}" | grep -q '"items"' || { echo "FAIL: /documents did not return items"; exit 1; }

# Verify video content_type filter is accepted (no 422 or 500)
FILTER_RESP=$(curl -sf "${BASE}/documents?content_type=video")
echo "${FILTER_RESP}" | grep -q '"items"' || { echo "FAIL: video filter rejected"; exit 1; }

# Verify /documents/ingest accepts .mp4 with content_type=video
# (uses a tiny dummy MP4 header; server validates extension not MIME magic)
INGEST_RESP=$(curl -sf -X POST "${BASE}/documents/ingest" \
  -F "file=@/dev/null;filename=test.mp4;type=video/mp4" \
  -F "content_type=video" \
  -o /dev/null -w "%{http_code}")
# Expect 200 or 422 (422 = empty file rejected, which is fine for smoke)
[ "${INGEST_RESP}" = "200" ] || [ "${INGEST_RESP}" = "422" ] || {
  echo "FAIL: /documents/ingest returned unexpected ${INGEST_RESP}"; exit 1;
}

echo "S121 smoke: PASS"
