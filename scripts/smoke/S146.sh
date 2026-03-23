#!/usr/bin/env bash
# Smoke test for S146: PDF viewer endpoints (/file and /pdf-meta).
# Requires the backend to be running on localhost:7820.

set -euo pipefail
BASE="http://localhost:7820"

# 1. Health check
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. GET /documents/{nonexistent}/file should return 404
HTTP_FILE=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/documents/nonexistent-s146-doc-id/file")
if [ "$HTTP_FILE" != "404" ]; then
  echo "FAIL: expected 404 for nonexistent doc /file, got ${HTTP_FILE}"
  exit 1
fi

# 3. GET /documents/{nonexistent}/pdf-meta should return 404
HTTP_META=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/documents/nonexistent-s146-doc-id/pdf-meta")
if [ "$HTTP_META" != "404" ]; then
  echo "FAIL: expected 404 for nonexistent doc /pdf-meta, got ${HTTP_META}"
  exit 1
fi

echo "PASS: S146 -- /file and /pdf-meta endpoints respond correctly (404 for nonexistent doc)"
