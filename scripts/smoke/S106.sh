#!/usr/bin/env bash
# S106 smoke: create note with section_id, verify round-trip via GET /notes
# Requires a running backend at localhost:7820
set -euo pipefail
source "$(dirname "$0")/lib.sh"

DOC_ID="smoke-doc-s106"
SECTION_ID="smoke-section-001"

echo "S106 [1/2]: Create note with section_id..."
CREATE=$(curl -sf -X POST "${BASE}/notes" \
  -H "Content-Type: application/json" \
  -d "{\"content\":\"S106 smoke note\",\"document_id\":\"${DOC_ID}\",\"section_id\":\"${SECTION_ID}\"}")
echo "$CREATE" | grep -q "\"section_id\":\"${SECTION_ID}\"" || { echo "FAIL: section_id missing from create response"; exit 1; }
echo "PASS: create note returns section_id"

echo "S106 [2/2]: List notes for document, verify section_id..."
LIST=$(curl -sf "${BASE}/notes?document_id=${DOC_ID}")
echo "$LIST" | grep -q "\"section_id\":\"${SECTION_ID}\"" || { echo "FAIL: section_id missing from list response"; exit 1; }
echo "PASS: list notes returns section_id"

echo "S106: ALL CHECKS PASSED"
