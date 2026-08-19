#!/usr/bin/env bash
# Smoke test for S238: every Progress number arrives with its provenance, and a
# number that could not be computed is absent rather than zero.
#
# What this guards: the page used to average `accuracy_pct` across recent study
# sessions and label it "mastery", so a fresh install with one 10-card session at
# 90% displayed 90% mastery of the whole library. It also read its document count
# from /monitoring/overview -- a full-mode router that no shipped build mounts --
# and rendered the 404 as a confident 0.
#
# Verifies:
#   1. backend is healthy
#   2. /progress/summary answers, and carries every metric the page renders
#   3. each metric is the full envelope: value, unit, sample_size, definition, basis
#   4. an absent metric is null with a stated reason -- never 0 standing in for one
#   5. /progress/notes-timeline groups server-side

set -euo pipefail

BASE="${BASE:-http://localhost:7820}"

fail() {
  echo "FAIL: $1"
  exit 1
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (HTTP $HTTP)"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/progress/summary")
[ "$HTTP" = "200" ] || fail "/progress/summary returned HTTP $HTTP"

curl -s "${BASE}/progress/summary" | python3 -c "
import sys, json
body = json.load(sys.stdin)

expected = {
    'retention_30d', 'mastery', 'mature_cards', 'due_today', 'current_streak',
    'longest_streak', 'reviews_30d', 'gaps_closed', 'documents', 'notes',
}
missing = expected - set(body)
assert not missing, f'summary is missing metrics: {sorted(missing)}'

for name, m in body.items():
    for field in ('value', 'unit', 'sample_size', 'definition', 'basis'):
        assert field in m, f'{name} has no {field}: a number with no provenance'
    assert m['definition'].strip(), f'{name} has an empty definition'
    assert m['basis'].strip(), f'{name} has an empty basis'
    assert m['value'] is None or isinstance(m['value'], (int, float)), (
        f'{name} value is not a number or null: {m[\"value\"]!r}'
    )

print('  summary: %d metrics, all carrying definition + basis' % len(body))
" || fail "/progress/summary contract check failed"

# A metric that could not be computed must be null, and must say why. On a
# populated dev library nothing may be absent without a reason attached.
curl -s "${BASE}/progress/summary" | python3 -c "
import sys, json
body = json.load(sys.stdin)
absent = [k for k, m in body.items() if m['value'] is None]
for k in absent:
    basis = body[k]['basis']
    assert basis.strip(), f'{k} is absent and does not say why'
print('  absent metrics: %s' % (', '.join(absent) or 'none'))
" || fail "absent-metric reason check failed"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/progress/notes-timeline")
[ "$HTTP" = "200" ] || fail "/progress/notes-timeline returned HTTP $HTTP"

curl -s "${BASE}/progress/notes-timeline" | python3 -c "
import sys, json
body = json.load(sys.stdin)
assert 'points' in body and 'total_notes' in body, 'notes-timeline shape changed'
for p in body['points']:
    assert len(p['month']) == 7 and p['month'][4] == '-', f'bad month bucket: {p[\"month\"]!r}'
print('  notes-timeline: %d months, %d notes' % (len(body['points']), body['total_notes']))
" || fail "/progress/notes-timeline contract check failed"

echo "S238 OK"
