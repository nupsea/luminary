#!/usr/bin/env bash
# Smoke test for S134 — Vision LLM image analysis
# Usage: ./scripts/smoke/S134.sh <document_id>
# Requires: backend running at localhost:8000

set -euo pipefail

DOC_ID="${1:-}"
if [ -z "$DOC_ID" ]; then
  echo "Usage: $0 <document_id>"
  echo "Pass a document_id that has been ingested and has images extracted."
  exit 1
fi

echo "S134 smoke test — document_id=$DOC_ID"

# Check images endpoint responds 200
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/documents/${DOC_ID}/images")
if [ "$STATUS" -ne 200 ]; then
  echo "FAIL: GET /documents/${DOC_ID}/images returned HTTP $STATUS (expected 200)"
  exit 1
fi
echo "PASS: images endpoint returned HTTP 200"

# Check enrichment jobs endpoint includes image_analyze job type
JOBS=$(curl -s "http://localhost:8000/documents/${DOC_ID}/enrichment")
python3 -c "
import sys, json
try:
    jobs = json.loads('''${JOBS}''')
    types = [j.get('job_type') for j in jobs]
    if 'image_analyze' not in types:
        print(f'FAIL: image_analyze job not found in enrichment jobs: {types}')
        sys.exit(1)
    print(f'PASS: image_analyze job present in enrichment jobs')
except Exception as e:
    print(f'FAIL: could not parse enrichment response: {e}')
    sys.exit(1)
"

echo "S134 smoke test passed"
