#!/usr/bin/env bash
# Smoke test for S68: App startup readiness — backend responds to GET /documents
set -euo pipefail

BASE="http://localhost:8000"

echo "S68 smoke: waiting 2s then GET /documents"
sleep 2
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/documents")
if [ "$STATUS" != "200" ]; then
  echo "FAIL: GET /documents returned HTTP $STATUS (backend may not be running)"
  exit 1
fi
echo "PASS: GET /documents returned 200 within 2s of startup"
