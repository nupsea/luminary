#!/usr/bin/env bash
# Smoke test for S177: Progress tab / Admin route
# Verifies:
#   1. GET /evals/runs still returns 200 (eval history lives on the Quality console)
#   2. GET /monitoring/overview still returns 200
#   3. GET /study/history still returns 200
#   4. GET /study/due-count still returns 200
# Note: frontend routing changes are not verifiable via curl; verified via tsc + manual check.

set -euo pipefail

BASE="${LUMINARY_API:-http://localhost:8000}"

echo "=== S177 Smoke: Progress tab / Admin route ==="

# 1. Monitoring overview still works (used by Admin page and Progress page stats)
echo "[1/4] GET /monitoring/overview"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/monitoring/overview")
if [ "$STATUS" != "200" ]; then
  echo "FAIL: /monitoring/overview returned $STATUS (expected 200)"
  exit 1
fi
echo "  -> $STATUS OK"

# 2. Eval runs still work (Quality console)
echo "[2/4] GET /evals/runs"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/evals/runs")
if [ "$STATUS" != "200" ]; then
  echo "FAIL: /evals/runs returned $STATUS (expected 200)"
  exit 1
fi
echo "  -> $STATUS OK"

# 3. Study history endpoint (used by Progress page activity chart)
echo "[3/4] GET /study/history?days=30"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/study/history?days=30")
if [ "$STATUS" != "200" ]; then
  echo "FAIL: /study/history returned $STATUS (expected 200)"
  exit 1
fi
echo "  -> $STATUS OK"

# 4. Study due-count endpoint (used by Progress page stats)
echo "[4/4] GET /study/due-count"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/study/due-count")
if [ "$STATUS" != "200" ]; then
  echo "FAIL: /study/due-count returned $STATUS (expected 200)"
  exit 1
fi
echo "  -> $STATUS OK"

echo ""
echo "=== S177 smoke PASSED ==="
