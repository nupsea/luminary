#!/usr/bin/env bash
# Smoke test for S85 — RAGAS eval results panel
# Verifies GET /evals/results returns HTTP 200 with a JSON array body.
# Verifies POST /evals/run with dataset=book returns HTTP 202.
set -euo pipefail

BASE="http://localhost:7820"

echo "S85 smoke: GET /evals/results"
BODY=$(curl -sf "$BASE/evals/results")
STATUS=$(curl -so /dev/null -w "%{http_code}" "$BASE/evals/results")
if [ "$STATUS" != "200" ]; then
  echo "FAIL: GET /evals/results returned HTTP $STATUS (expected 200)"
  exit 1
fi
# Body must be a JSON array (starts with '[')
FIRST=$(echo "$BODY" | tr -d ' \n' | cut -c1)
if [ "$FIRST" != "[" ]; then
  echo "FAIL: body is not a JSON array: $BODY"
  exit 1
fi
echo "PASS: GET /evals/results -> HTTP 200, JSON array"

echo "S85 smoke: POST /evals/run {dataset: book}"
RUN_STATUS=$(curl -so /dev/null -w "%{http_code}" -X POST "$BASE/evals/run" \
  -H "Content-Type: application/json" \
  -d '{"dataset": "book"}')
if [ "$RUN_STATUS" != "202" ]; then
  echo "FAIL: POST /evals/run returned HTTP $RUN_STATUS (expected 202)"
  exit 1
fi
echo "PASS: POST /evals/run -> HTTP 202"

echo "S85 smoke: all checks passed"
