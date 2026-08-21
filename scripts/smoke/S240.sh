#!/usr/bin/env bash
# Smoke test for S240: time on task is accrued between heartbeats, and a gap the
# user spent away is never credited.
#
# What this guards: the hub's "this week" pie splits a week four ways, and the
# only honest source for reading and editing time is a client sample -- the
# server sees requests, and a reader who opens a document and reads for twenty
# minutes issues one. What is measured is time with the surface open and
# visible, which is not attention, and the wire contract must keep the two
# distinguishable rather than quietly promoting one to the other.
#
# Verifies:
#   1. backend is healthy
#   2. POST /engagement/heartbeat answers and states its own cadence
#   3. the first beat of a stretch credits nothing -- there is nothing to
#      measure from until a second sample arrives
#   4. an unknown activity is refused rather than silently recorded
#   5. /home/overview carries seconds_by_activity, zero-filled across every
#      activity, so a missing slice cannot be read as a measured zero

set -euo pipefail

BASE="${BASE:-http://localhost:7820}"

fail() {
  echo "FAIL: $1"
  exit 1
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (HTTP $HTTP)"

BEAT=$(curl -s -X POST "${BASE}/engagement/heartbeat" \
  -H 'Content-Type: application/json' \
  -d '{"activity":"document","member_id":"smoke-s240"}')

echo "$BEAT" | python3 -c "
import sys, json
body = json.load(sys.stdin)
for field in ('seconds_credited', 'heartbeat_seconds'):
    assert field in body, f'heartbeat response has no {field}'
assert body['heartbeat_seconds'] > 0, 'the client is told to beat every 0 seconds'
assert body['seconds_credited'] == 0, (
    'the first beat of a stretch credited %r; nothing precedes it to measure from'
    % body['seconds_credited']
)
print('  heartbeat: credited %ds, cadence %ds'
      % (body['seconds_credited'], body['heartbeat_seconds']))
" || fail "heartbeat contract check failed"

# An activity the pie cannot draw is a client bug. Recording it silently would
# lose the time into a slice nothing renders.
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/engagement/heartbeat" \
  -H 'Content-Type: application/json' \
  -d '{"activity":"doomscrolling"}')
[ "$HTTP" = "422" ] || fail "an unknown activity returned HTTP $HTTP, expected 422"

curl -s "${BASE}/home/overview" | python3 -c "
import sys, json
body = json.load(sys.stdin)
stats = body.get('weekly_stats')
assert stats is not None, '/home/overview carries no weekly_stats'
by = stats.get('seconds_by_activity')
assert isinstance(by, dict), 'weekly_stats has no seconds_by_activity mapping'

expected = {'document', 'note', 'review', 'study'}
missing = expected - set(by)
assert not missing, f'seconds_by_activity is not zero-filled, missing: {sorted(missing)}'
for name, seconds in by.items():
    assert isinstance(seconds, int) and seconds >= 0, f'{name} is {seconds!r}'

# Distinct bases: minutes_studied is study-session wall clock, the pie is
# foreground sampling. Drawing them as one number is what this keeps apart.
assert 'minutes_studied' in stats, 'weekly_stats lost minutes_studied'
print('  weekly: %s' % ', '.join('%s=%ds' % kv for kv in sorted(by.items())))

# A percentage the reader cannot check is not a figure worth printing, so the
# continue lane carries the counts its ratio is taken from. Without these the
# hub is back to a bare '9%'.
for item in body.get('continue_reading') or []:
    for field in ('sections_read', 'sections_total'):
        assert field in item, f'continue_reading item has no {field}'
        assert isinstance(item[field], int), f'{field} is {item[field]!r}'
    assert item['sections_total'] > 0, 'a continue item with no sections cannot show progress'
    assert 0 <= item['sections_read'] <= item['sections_total'], (
        'sections_read %s is outside 0..%s' % (item['sections_read'], item['sections_total'])
    )
print('  continue_reading: %d item(s) carry section counts' % len(body.get('continue_reading') or []))
" || fail "/home/overview contract check failed"

echo "S240 OK"
