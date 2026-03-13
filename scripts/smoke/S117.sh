#!/usr/bin/env bash
# S117 smoke test: verify GET /graph/learning-path responds 200 with expected shape.
set -euo pipefail

BASE="http://localhost:8000"

echo "S117 smoke: GET /graph/learning-path with unknown entity returns 200 and empty nodes"
resp=$(curl -sf "${BASE}/graph/learning-path?start_entity=test_concept&document_id=nonexistent_doc")
echo "Response: $resp"

# Verify the response contains the expected JSON keys
echo "$resp" | python3 -c "
import sys, json
data = json.load(sys.stdin)
assert 'start_entity' in data, 'missing start_entity'
assert 'document_id' in data, 'missing document_id'
assert 'nodes' in data, 'missing nodes'
assert 'edges' in data, 'missing edges'
assert data['nodes'] == [], f'expected empty nodes, got {data[\"nodes\"]}'
print('PASS: /graph/learning-path shape is correct')
"
