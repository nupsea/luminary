#!/usr/bin/env bash
# Smoke test for S114 - Struggling Cards endpoint
# Requires: live backend at http://localhost:8000
set -euo pipefail

BASE="http://localhost:8000"

echo "=== S114 smoke: Struggling Cards ==="

# 1. GET /study/struggling -- no document filter, should return list
echo "[1] GET /study/struggling (no filter)"
RESP=$(curl -sf "${BASE}/study/struggling")
echo "    Response: ${RESP}"
echo "${RESP}" | python3 -c "import sys, json; d=json.load(sys.stdin); assert isinstance(d, list), 'expected list'"
echo "    PASS"

# 2. GET /study/struggling with custom threshold and days
echo "[2] GET /study/struggling with threshold=5&days=30"
RESP2=$(curl -sf "${BASE}/study/struggling?again_threshold=5&days=30")
echo "    Response: ${RESP2}"
echo "${RESP2}" | python3 -c "import sys, json; d=json.load(sys.stdin); assert isinstance(d, list), 'expected list'"
echo "    PASS"

# 3. GET /study/struggling with a fake doc_id -- should return empty list
echo "[3] GET /study/struggling?document_id=nonexistent"
RESP3=$(curl -sf "${BASE}/study/struggling?document_id=nonexistent-doc-id")
echo "    Response: ${RESP3}"
echo "${RESP3}" | python3 -c "import sys, json; d=json.load(sys.stdin); assert d == [], f'expected [] got {d}'"
echo "    PASS"

echo "=== S114 smoke: ALL PASS ==="
