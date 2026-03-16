#!/usr/bin/env bash
# S136 smoke test: verify GET /graph/entities/{doc_id}?type=COMPONENT returns 200
# with correct response shape (entities key present).
# Note: this test requires a live server at localhost:7820.
set -euo pipefail
BASE="http://localhost:7820"

echo "S136 smoke: GET /graph/entities/nonexistent_doc?type=COMPONENT returns 200"
resp=$(curl -sf "${BASE}/graph/entities/nonexistent_doc_id?type=COMPONENT")
echo "Response: $resp"
echo "$resp" | python3 -c "
import sys, json
data = json.load(sys.stdin)
assert 'entities' in data, f'missing entities key in response: {data}'
assert isinstance(data['entities'], list), 'entities must be a list'
print('PASS: /graph/entities?type=COMPONENT shape correct, entities is list')
"
echo "S136 smoke: PASS"
