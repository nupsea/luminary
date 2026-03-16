#!/usr/bin/env bash
# Smoke test for S148: POST /qa returns HTTP 200 and SSE done event includes source_citations field.
# Does not require any documents to be ingested -- just verifies the field is present in the done event.

set -euo pipefail
BASE="http://localhost:7820"

HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

TMPFILE=$(mktemp)
HTTP_QA=$(curl -s -o "${TMPFILE}" -w "%{http_code}" \
  -X POST "${BASE}/qa" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is this about?","document_ids":[],"scope":"all"}')

if [ "$HTTP_QA" != "200" ]; then
  echo "FAIL: expected 200 for POST /qa, got ${HTTP_QA}"
  cat "${TMPFILE}"
  rm -f "${TMPFILE}"
  exit 1
fi

# The done event must include source_citations field (even if empty array)
if ! grep -q '"done":true' "${TMPFILE}"; then
  echo "FAIL: expected done event in SSE body"
  cat "${TMPFILE}"
  rm -f "${TMPFILE}"
  exit 1
fi

if ! grep -q '"source_citations"' "${TMPFILE}"; then
  echo "FAIL: expected source_citations field in done event"
  cat "${TMPFILE}"
  rm -f "${TMPFILE}"
  exit 1
fi

rm -f "${TMPFILE}"
echo "PASS: S148 -- POST /qa returned HTTP 200 with done event containing source_citations"
