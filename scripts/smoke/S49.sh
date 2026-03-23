#!/usr/bin/env bash
# Smoke test for S49: Viz tab — GET /graph endpoint returns 200 with nodes/edges structure.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# 1. GET /graph with no doc_ids — must return 200 with nodes array
BODY=$(curl -sf "${BASE}/graph?doc_ids=")
if [ -z "$BODY" ]; then
  echo "FAIL: GET /graph returned empty body"
  exit 1
fi

# 2. Verify response contains "nodes" and "edges" keys
if ! echo "$BODY" | grep -q '"nodes"'; then
  echo "FAIL: GET /graph response missing 'nodes' key"
  exit 1
fi
if ! echo "$BODY" | grep -q '"edges"'; then
  echo "FAIL: GET /graph response missing 'edges' key"
  exit 1
fi

echo "PASS: GET /graph returns 200 with nodes and edges"
