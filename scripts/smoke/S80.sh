#!/usr/bin/env bash
# Smoke test for S80: V2 integration tests gate.
# Sends 4 POST /qa calls with different intent types; all must return HTTP 200.
# Requires the backend to be running on localhost:8000.

set -euo pipefail

BASE="http://localhost:8000"
FAIL=0

qa_check() {
  local label="$1"
  local question="$2"
  local scope="${3:-all}"
  local tmp_file="/tmp/s80_qa_${RANDOM}.txt"

  echo "Testing $label ..."
  HTTP_CODE=$(curl -s --max-time 30 -o "$tmp_file" -w "%{http_code}" \
    -X POST "${BASE}/qa" \
    -H "Content-Type: application/json" \
    -d "{\"question\": \"${question}\", \"document_ids\": [], \"scope\": \"${scope}\"}")

  if [ "$HTTP_CODE" != "200" ]; then
    echo "FAIL: $label returned HTTP ${HTTP_CODE}"
    cat "$tmp_file"
    FAIL=1
    return
  fi

  HAS_DONE=$(python3 -c "
import json, sys
content = open('${tmp_file}').read()
for line in content.split('\n'):
    if not line.startswith('data: '):
        continue
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
    echo "PASS: $label returned HTTP 200 with done event"
  else
    echo "FAIL: $label had no done event"
    FAIL=1
  fi
}

# 4 intent types
qa_check "summary intent"     "Give me an overview of this book"
qa_check "factual intent"     "Who is the White Rabbit?"
qa_check "relational intent"  "How are Odysseus and Telemachus related?"
qa_check "comparative intent" "Compare Alice versus the Time Traveller"

if [ "$FAIL" -ne 0 ]; then
  echo ""
  echo "FAIL: One or more S80 smoke checks failed"
  exit 1
fi

echo ""
echo "PASS: All S80 /qa intent routing calls returned HTTP 200 with done events"
exit 0
