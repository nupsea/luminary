#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
# A 200 queues a real download from youtube.com.
smoke_requires_internet

echo "S122: checking /documents/ingest-url endpoint exists..."
resp=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${BASE}/documents/ingest-url" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}')

# 503 = yt-dlp not installed (acceptable), 200 = success, 400 = bad URL
if [[ "$resp" == "503" || "$resp" == "200" || "$resp" == "400" ]]; then
  echo "S122: ingest-url endpoint responds correctly (HTTP $resp)"
else
  echo "S122: unexpected HTTP $resp from ingest-url"
  exit 1
fi

echo "S122: PASS"
