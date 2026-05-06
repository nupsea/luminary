#!/usr/bin/env bash
# Smoke test for S225: graph-augmented deterministic query expansion.
#
# Verifies:
#   1. backend is healthy
#   2. GET /search?q=...&graph_expand=true returns HTTP 200 (default lever ON)
#   3. GET /search?q=...&graph_expand=false returns HTTP 200 (lever OFF, ablation)
#   4. response is well-formed JSON with a "results" key
#
# Requires the backend running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# 1. Backend health.
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. graph_expand=true (default).
HTTP_ON=$(curl -s -o /tmp/s225_on.json -w "%{http_code}" \
  "${BASE}/search?q=Holmes&graph_expand=true&limit=3")
if [ "$HTTP_ON" != "200" ]; then
  echo "FAIL: /search?graph_expand=true returned ${HTTP_ON}"
  cat /tmp/s225_on.json
  exit 1
fi
grep -q '"results"' /tmp/s225_on.json \
  || { echo "FAIL: /search response missing 'results' key"; cat /tmp/s225_on.json; exit 1; }

# 3. graph_expand=false (ablation mode).
HTTP_OFF=$(curl -s -o /tmp/s225_off.json -w "%{http_code}" \
  "${BASE}/search?q=Holmes&graph_expand=false&limit=3")
if [ "$HTTP_OFF" != "200" ]; then
  echo "FAIL: /search?graph_expand=false returned ${HTTP_OFF}"
  cat /tmp/s225_off.json
  exit 1
fi
grep -q '"results"' /tmp/s225_off.json \
  || { echo "FAIL: /search response missing 'results' key"; cat /tmp/s225_off.json; exit 1; }

echo "PASS: S225 -- /search accepts graph_expand=true|false"
