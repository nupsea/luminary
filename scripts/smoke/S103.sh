#!/usr/bin/env bash
# S103 smoke test: POST /qa returns HTTP 200 SSE response (Ollama online path)
set -euo pipefail
source "$(dirname "$0")/lib.sh"

echo "S103: POST /qa returns HTTP 200..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${BASE}/qa" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is this about?"}')

if [ "$STATUS" != "200" ]; then
  echo "FAIL: POST /qa returned $STATUS (expected 200)"
  exit 1
fi

echo "PASS: POST /qa returned 200"
