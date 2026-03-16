#!/usr/bin/env bash
# S145 smoke test: concept mastery endpoints return 200 with empty data for nonexistent IDs
set -e
BASE="http://localhost:8000"

echo "S145 smoke: GET /mastery/concepts"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  "${BASE}/mastery/concepts?document_ids=nonexistent-00000000")
[ "$STATUS" = "200" ] || { echo "FAIL: /mastery/concepts returned $STATUS"; exit 1; }

echo "S145 smoke: GET /mastery/heatmap"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  "${BASE}/mastery/heatmap?document_id=nonexistent-00000000")
[ "$STATUS" = "200" ] || { echo "FAIL: /mastery/heatmap returned $STATUS"; exit 1; }

echo "S145 smoke PASSED"
