#!/usr/bin/env bash
# Smoke test for S144: Feynman technique mode
# Tests POST /feynman/sessions returns 201 (success) or 503 (Ollama offline).
# Both are valid since Ollama may not be running during smoke test execution.
set -euo pipefail

BASE="http://localhost:7820"

# Get first document id from library
DOC_ID=$(curl -sf "$BASE/documents" | python3 -c "
import sys, json
docs = json.load(sys.stdin)
if docs:
    print(docs[0]['id'])
" 2>/dev/null || echo "")

if [ -z "$DOC_ID" ]; then
  echo "SKIP: no documents in library -- cannot test Feynman session creation"
  exit 0
fi

STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/feynman/sessions" \
  -H "Content-Type: application/json" \
  -d "{\"document_id\": \"$DOC_ID\", \"concept\": \"smoke test concept\"}")

if [ "$STATUS" = "201" ] || [ "$STATUS" = "503" ]; then
  echo "PASS: POST /feynman/sessions returned $STATUS (expected 201 or 503)"
  exit 0
else
  echo "FAIL: POST /feynman/sessions returned $STATUS (expected 201 or 503)"
  exit 1
fi
