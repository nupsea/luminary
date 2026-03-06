#!/usr/bin/env bash
# Smoke test for S78: strategy nodes — summary_lookup, graph_traversal, comparative, search.
# POST /qa twice with different question types; both must return HTTP 200 within 30 seconds.
# Requires the backend to be running on localhost:8000.

set -euo pipefail

BASE="http://localhost:8000"

# ---------------------------------------------------------------------------
# Helper: POST /qa and check response
# ---------------------------------------------------------------------------

qa_check() {
  local label="$1"
  local question="$2"
  local tmp_file="/tmp/s78_qa_${RANDOM}.txt"

  echo "Testing $label ..."
  HTTP_CODE=$(curl -s --max-time 30 -o "$tmp_file" -w "%{http_code}" \
    -X POST "${BASE}/qa" \
    -H "Content-Type: application/json" \
    -d "{\"question\": \"${question}\", \"document_ids\": [], \"scope\": \"all\"}")

  if [ "$HTTP_CODE" != "200" ]; then
    echo "FAIL: $label returned HTTP ${HTTP_CODE} (expected 200)"
    cat "$tmp_file"
    return 1
  fi

  HAS_DONE=$(python3 -c "
import json, sys
content = open('${tmp_file}').read()
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

  if [ "\$HAS_DONE" == "yes" ]; then
    echo "PASS: $label returned HTTP 200 with done event"
  else
    echo "FAIL: $label response did not contain a done event"
    cat "$tmp_file"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# Test 1: Factual question — exercises search_node
# ---------------------------------------------------------------------------
qa_check "factual (search_node)" "Who is Achilles?"

# ---------------------------------------------------------------------------
# Test 2: Summary question — exercises summary_node (or fallthrough to search)
# ---------------------------------------------------------------------------
qa_check "summary (summary_node)" "Summarize this document"

echo ""
echo "PASS: All S78 /qa calls returned HTTP 200 within 30 seconds"
exit 0
