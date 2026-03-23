#!/usr/bin/env bash
# Smoke test for S90: Notes auto-tagging -- POST /notes/{id}/suggest-tags.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# 1. Create a note with sufficient content for tagging
CREATE=$(curl -sf -X POST "${BASE}/notes" \
  -H "Content-Type: application/json" \
  -d '{"content":"The study of machine learning and neural networks has transformed artificial intelligence research over the past decade.","tags":[]}')
if [ -z "$CREATE" ]; then
  echo "FAIL: POST /notes returned empty body"
  exit 1
fi

NOTE_ID=$(echo "$CREATE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
if [ -z "$NOTE_ID" ]; then
  echo "FAIL: POST /notes response missing id"
  exit 1
fi

# 2. Call suggest-tags -- must return HTTP 200 with tags array
HTTP_CODE=$(curl -s -o /tmp/s90_suggest.json -w "%{http_code}" -X POST "${BASE}/notes/${NOTE_ID}/suggest-tags")
if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: POST /notes/${NOTE_ID}/suggest-tags returned ${HTTP_CODE} (expected 200)"
  exit 1
fi

TAGS=$(python3 -c "import json; d=json.load(open('/tmp/s90_suggest.json')); print(type(d.get('tags')).__name__)")
if [ "$TAGS" != "list" ]; then
  echo "FAIL: suggest-tags response missing 'tags' list"
  exit 1
fi

# 3. suggest-tags on nonexistent note must return 404
HTTP_404=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/notes/nonexistent-id/suggest-tags")
if [ "$HTTP_404" != "404" ]; then
  echo "FAIL: POST /notes/nonexistent-id/suggest-tags returned ${HTTP_404} (expected 404)"
  exit 1
fi

# 4. Clean up
curl -s -X DELETE "${BASE}/notes/${NOTE_ID}" -o /dev/null || true

echo "PASS: S90 suggest-tags returns 200+tags for existing note and 404 for missing note"
