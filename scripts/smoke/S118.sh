#!/usr/bin/env bash
# Smoke test for S118: GET /study/due-count endpoint
set -euo pipefail

BASE="${API_BASE:-http://localhost:8000}"

status=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/study/due-count")
if [ "$status" != "200" ]; then
  echo "FAIL: GET /study/due-count expected 200, got $status"
  exit 1
fi

body=$(curl -s "$BASE/study/due-count")
if ! echo "$body" | grep -q '"due_today"'; then
  echo "FAIL: response missing due_today field. Body: $body"
  exit 1
fi

echo "PASS: GET /study/due-count returned 200 with due_today field"
