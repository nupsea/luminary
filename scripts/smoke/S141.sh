#!/usr/bin/env bash
set -euo pipefail
BASE="http://localhost:8000"

RESP=$(curl -sf "$BASE/graph/concepts/linked")
echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'clusters' in d, f'missing clusters key: {d}'
print(f'PASS: GET /graph/concepts/linked returned {len(d[\"clusters\"])} clusters')
"
