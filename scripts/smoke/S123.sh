#!/usr/bin/env bash
# Smoke test for S123: EPUB and Kindle ingestion
# Calls localhost:7820 over real HTTP. No mocking.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:7820}"

echo "S123 smoke: Kindle My Clippings.txt ingest"

# Create a minimal Kindle clippings file
# `mktemp /tmp/..._XXXXXX.txt` is the GNU form: BSD mktemp wants the Xs last and
# fails "mkstemp failed ... File exists" once a run has left one behind, so this
# script worked once per machine. A temp directory keeps the filename meaningful
# and unique per run; the upload names the file itself on line below.
TMPDIR_S123=$(mktemp -d)
trap 'rm -rf "$TMPDIR_S123"' EXIT
TMPFILE="$TMPDIR_S123/My_Clippings.txt"
cat >"$TMPFILE" <<'CLIPPINGS'
==========
A Brief History of Time (Stephen Hawking)
- Your Highlight on page 42 | Location 512-514 | Added on Monday, January 1, 2024 12:00:00 AM

We find ourselves in a bewildering world.
==========
A Brief History of Time (Stephen Hawking)
- Your Highlight on page 55 | Location 700-702 | Added on Monday, January 1, 2024 12:05:00 AM

The universe is governed by scientific laws.
==========
CLIPPINGS

# POST to ingest-kindle
HTTP_STATUS=$(curl -s -o /tmp/s123_response.json -w "%{http_code}" \
  -X POST "${BASE_URL}/documents/ingest-kindle" \
  -F "file=@${TMPFILE};filename=My Clippings.txt;type=text/plain")


if [ "$HTTP_STATUS" != "200" ]; then
  echo "FAIL: ingest-kindle returned HTTP $HTTP_STATUS"
  cat /tmp/s123_response.json
  exit 1
fi

BOOK_COUNT=$(python3 -c "import json,sys; d=json.load(open('/tmp/s123_response.json')); print(d.get('book_count',0))")
if [ "$BOOK_COUNT" -lt 1 ]; then
  echo "FAIL: book_count=$BOOK_COUNT, expected >= 1"
  cat /tmp/s123_response.json
  exit 1
fi

echo "PASS: ingest-kindle returned HTTP $HTTP_STATUS, book_count=$BOOK_COUNT"
echo "S123 smoke: PASS"
