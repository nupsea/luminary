#!/usr/bin/env bash
# Smoke test for S159 -- comparative self-assessment: model explanation diff view.
# Verifies that GET /feynman/sessions endpoint is reachable (HTTP 200).
# Model explanation streaming and diff view are covered by backend/frontend unit tests.
set -euo pipefail

BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  "${BASE}/feynman/sessions?document_id=smoke-check")

if [ "$STATUS" = "200" ]; then
  echo "S159 smoke: GET /feynman/sessions returns 200 -- OK"
else
  echo "S159 smoke: expected 200, got $STATUS" >&2
  exit 1
fi

echo "S159 smoke PASSED"
