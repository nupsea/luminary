#!/usr/bin/env bash
# Smoke test for S129: RAGAS eval pipeline fix
# Verifies GET /evals/results returns HTTP 200 with a JSON array body.
set -euo pipefail

BASE="${BACKEND_URL:-http://localhost:7820}"

echo "=== S129 smoke test: GET /evals/results ==="

RESPONSE=$(curl -sf -o /tmp/s129_evals.json -w "%{http_code}" "${BASE}/evals/results")
if [ "$RESPONSE" != "200" ]; then
  echo "FAIL: GET /evals/results returned HTTP ${RESPONSE}, expected 200"
  exit 1
fi

# Verify response body is a JSON array (even if empty)
python3 -c "
import json, sys
with open('/tmp/s129_evals.json') as f:
    data = json.load(f)
assert isinstance(data, list), f'Expected list, got {type(data).__name__}'
print(f'OK: /evals/results returned {len(data)} item(s)')
"

echo "=== S129 smoke test PASSED ==="
