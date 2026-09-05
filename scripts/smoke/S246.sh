#!/usr/bin/env bash
# Smoke test for S246: GET /settings/llm/routing -- where each unit of work runs
set -euo pipefail

BASE="${BASE:-http://localhost:7820}"

echo "=== S246 Smoke: LLM routing report ==="

# 1. Health check
echo "--- Health check ---"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/health")
if [ "$HTTP" != "200" ]; then
  echo "FAIL: /health returned $HTTP"
  exit 1
fi
echo "OK: /health => 200"

# 2. The endpoint answers
echo "--- GET /settings/llm/routing ---"
TMPFILE=$(mktemp)
ROUTE_HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$BASE/settings/llm/routing")
BODY=$(cat "$TMPFILE")
rm -f "$TMPFILE"

if [ "$ROUTE_HTTP" != "200" ]; then
  echo "FAIL: GET /settings/llm/routing returned $ROUTE_HTTP"
  echo "$BODY" | head -5
  exit 1
fi
echo "OK: GET /settings/llm/routing => 200"

# 3. Shape, and the two consistency properties the UI depends on:
#    - every declared work id is present, so the table cannot render a gap
#    - leaves_device is exactly the off-device rows, so the summary line and the
#      rows it summarises cannot disagree on screen
echo "--- Validating shape and derived consistency ---"
echo "$BODY" | python3 -c "
import json, sys

REQUIRED = {
    'indexing', 'retrieval', 'transcription', 'extraction', 'enrichment',
    'figures', 'study_material', 'answering', 'learner_record',
}
STRUCTURAL = {'indexing', 'retrieval', 'transcription', 'extraction', 'learner_record'}

d = json.load(sys.stdin)
for key in ('mode', 'provider', 'work', 'leaves_device'):
    if key not in d:
        sys.exit(f'FAIL: response missing {key!r}')

if d['mode'] not in ('private', 'hybrid', 'cloud'):
    sys.exit(f'FAIL: unexpected mode {d[\"mode\"]!r}')

rows = {w['id']: w for w in d['work']}
missing = REQUIRED - set(rows)
if missing:
    sys.exit(f'FAIL: work rows missing: {sorted(missing)}')

for w in d['work']:
    for key in ('id', 'label', 'model', 'on_device', 'routable', 'why'):
        if key not in w:
            sys.exit(f'FAIL: work row {w.get(\"id\")!r} missing {key!r}')
    if not isinstance(w['on_device'], bool) or not isinstance(w['routable'], bool):
        sys.exit(f'FAIL: work row {w[\"id\"]!r} has a non-boolean flag')

derived = sorted(w['id'] for w in d['work'] if not w['on_device'])
if derived != sorted(d['leaves_device']):
    sys.exit(f'FAIL: leaves_device {sorted(d[\"leaves_device\"])} != off-device rows {derived}')

off_structural = STRUCTURAL & set(d['leaves_device'])
if off_structural:
    sys.exit(f'FAIL: work with no remote path reported off-device: {sorted(off_structural)}')

if rows['learner_record']['model'] is not None:
    sys.exit('FAIL: learner_record names a model; nothing there runs a model')

print(f'OK: mode={d[\"mode\"]} rows={len(d[\"work\"])} leaves_device={d[\"leaves_device\"] or \"[]\"}')
"

echo "=== S246 smoke: PASSED ==="
exit 0
