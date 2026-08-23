#!/usr/bin/env bash
# Smoke test for S92: Notes as chat context -- a notes-intent question to /qa.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"
NOTE_ID=""

cleanup() {
  if [ -n "$NOTE_ID" ]; then
    curl -s -o /dev/null -X DELETE "${BASE}/notes/${NOTE_ID}" || true
  fi
}
trap cleanup EXIT

# 1. Create a note to search against
CREATE_RESP=$(curl -s -X POST "${BASE}/notes" \
  -H "Content-Type: application/json" \
  -d '{"content":"The Cheshire Cat can vanish leaving only its grin","tags":[]}')
NOTE_ID=$(echo "$CREATE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

if [ -z "$NOTE_ID" ]; then
  echo "FAIL: POST /notes did not return an id"
  exit 1
fi

# 2. Ask the notes-intent question. `POST /chat/stream` is gone -- streaming
#    chat is served by `POST /qa`, which routes a notes-phrased question to the
#    notes path through the intent classifier (I-26). The subject of this script
#    is that notes reach chat as context, and that is where it happens now.
HTTP_CODE=$(curl -s -o /tmp/s92_chat.txt -w "%{http_code}" -X POST "${BASE}/qa" \
  -H "Content-Type: application/json" \
  -d '{"question":"what did I note about my reading","scope":"all"}')

if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: POST /qa returned ${HTTP_CODE} (expected 200)"
  cat /tmp/s92_chat.txt
  exit 1
fi

# 3. An answer, not an empty envelope. /qa streams SSE, so the payload is the
#    last `data:` line rather than the whole body.
python3 -c "
import json
lines = [l[6:] for l in open('/tmp/s92_chat.txt') if l.startswith('data: ')]
assert lines, 'no SSE data lines in the /qa response'
final = json.loads(lines[-1])
assert not final.get('error'), f\"/qa answered with {final['error']}\"
assert final.get('answer'), 'POST /qa returned no answer for a notes-intent question'
" || { echo 'FAIL: /qa returned no usable answer'; tail -c 400 /tmp/s92_chat.txt; exit 1; }

echo "PASS: S92 -- note created, /qa answers a notes-intent question"
