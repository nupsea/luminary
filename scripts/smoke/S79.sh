#!/usr/bin/env bash
# Smoke test for S79: pure context packer integrated into synthesize_node.
# POST /qa with a book-style question; assert HTTP 200, done event, response < 15s.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"
TMP_FILE="/tmp/s79_qa.txt"

echo "POSTing question to /qa ..."
START_TIME=$(date +%s)

HTTP_CODE=$(curl -s --max-time 15 -o "$TMP_FILE" -w "%{http_code}" \
  -X POST "${BASE}/qa" \
  -H "Content-Type: application/json" \
  -d '{"question": "What happens in book 1?", "document_ids": [], "scope": "all"}')

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: POST /qa returned ${HTTP_CODE} (expected 200)"
  cat "$TMP_FILE"
  exit 1
fi

if [ "$ELAPSED" -ge 15 ]; then
  echo "FAIL: POST /qa took ${ELAPSED}s (expected < 15s)"
  exit 1
fi

HAS_DONE=$(python3 -c "
import json, sys
content = open('${TMP_FILE}').read()
lines = [l for l in content.split('\n') if l.startswith('data: ')]
for line in lines:
    try:
        obj = json.loads(line[6:])
        if obj.get('done'):
            print('yes')
            sys.exit(0)
    except Exception:
        pass
print('no')
" 2>/dev/null || echo "no")

if [ "$HAS_DONE" == "yes" ]; then
  echo "PASS: POST /qa returned HTTP 200 with done event in ${ELAPSED}s"
else
  echo "FAIL: POST /qa response did not contain a done event"
  cat "$TMP_FILE"
  exit 1
fi

exit 0
