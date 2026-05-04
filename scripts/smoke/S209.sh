#!/usr/bin/env bash
# Smoke test for S209: global focus timer pill (frontend) -- exercises the
# /pomodoro/* endpoints the pill depends on (S208 backend).
# Verifies: GET /active 200/204 contract, GET /stats schema, and a
# round-trip start -> active -> abandon flow used by the pill on mount/refresh.
# Requires the backend running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# 1. Health
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. Clear any stale active session from a previous run.
ACTIVE_BODY=$(mktemp)
HTTP_ACTIVE=$(curl -s -o "${ACTIVE_BODY}" -w "%{http_code}" "${BASE}/pomodoro/active")
if [ "$HTTP_ACTIVE" = "200" ]; then
  EXISTING_ID=$(python3 -c "import json,sys; print(json.load(open('${ACTIVE_BODY}'))['id'])")
  curl -s -o /dev/null -X POST "${BASE}/pomodoro/${EXISTING_ID}/abandon" || true
fi
rm -f "${ACTIVE_BODY}"

# 3. GET /pomodoro/active should now be 204 (idle pill state on mount).
HTTP_IDLE=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/pomodoro/active")
if [ "$HTTP_IDLE" != "204" ]; then
  echo "FAIL: expected 204 on idle /pomodoro/active, got ${HTTP_IDLE}"
  exit 1
fi

# 4. POST /pomodoro/start with surface=read (Learning tab default) and
#    custom focus_minutes/break_minutes -- mirrors what the pill sends.
START_BODY=$(mktemp)
HTTP_START=$(curl -s -o "${START_BODY}" -w "%{http_code}" \
  -X POST "${BASE}/pomodoro/start" \
  -H "Content-Type: application/json" \
  -d '{"focus_minutes": 25, "break_minutes": 5, "surface": "read"}')
if [ "$HTTP_START" != "200" ]; then
  echo "FAIL: expected 200 for /pomodoro/start, got ${HTTP_START}"
  cat "${START_BODY}"
  rm -f "${START_BODY}"
  exit 1
fi
SESSION_ID=$(python3 -c "import json; d=json.load(open('${START_BODY}')); assert d['status']=='active'; assert d['surface']=='read'; assert d['focus_minutes']==25; print(d['id'])")
rm -f "${START_BODY}"

if [ -z "${SESSION_ID}" ]; then
  echo "FAIL: missing id in /pomodoro/start response"
  exit 1
fi

# 5. GET /pomodoro/active returns the session in shape the pill expects.
ACTIVE2=$(mktemp)
HTTP_ACT2=$(curl -s -o "${ACTIVE2}" -w "%{http_code}" "${BASE}/pomodoro/active")
if [ "$HTTP_ACT2" != "200" ]; then
  echo "FAIL: expected 200 on /pomodoro/active after start, got ${HTTP_ACT2}"
  rm -f "${ACTIVE2}"
  exit 1
fi
python3 -c "
import json
d = json.load(open('${ACTIVE2}'))
required = ['id','started_at','focus_minutes','break_minutes','status','surface','pause_accumulated_seconds']
for k in required:
    assert k in d, f'missing key: {k}'
assert d['id'] == '${SESSION_ID}'
assert d['status'] == 'active'
"
rm -f "${ACTIVE2}"

# 6. Pause then resume (mirrors pill controls).
HTTP_PAUSE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/pomodoro/${SESSION_ID}/pause")
if [ "$HTTP_PAUSE" != "200" ]; then
  echo "FAIL: pause expected 200, got ${HTTP_PAUSE}"
  exit 1
fi
HTTP_RESUME=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/pomodoro/${SESSION_ID}/resume")
if [ "$HTTP_RESUME" != "200" ]; then
  echo "FAIL: resume expected 200, got ${HTTP_RESUME}"
  exit 1
fi

# 7. Stop / abandon (pill Stop control returns to idle).
HTTP_STOP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/pomodoro/${SESSION_ID}/abandon")
if [ "$HTTP_STOP" != "200" ]; then
  echo "FAIL: abandon expected 200, got ${HTTP_STOP}"
  exit 1
fi

# 8. GET /pomodoro/active is back to 204.
HTTP_ACT3=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/pomodoro/active")
if [ "$HTTP_ACT3" != "204" ]; then
  echo "FAIL: /pomodoro/active expected 204 after abandon, got ${HTTP_ACT3}"
  exit 1
fi

# 9. GET /pomodoro/stats returns the schema the popover renders.
STATS_BODY=$(mktemp)
HTTP_STATS=$(curl -s -o "${STATS_BODY}" -w "%{http_code}" "${BASE}/pomodoro/stats")
if [ "$HTTP_STATS" != "200" ]; then
  echo "FAIL: stats expected 200, got ${HTTP_STATS}"
  rm -f "${STATS_BODY}"
  exit 1
fi
python3 -c "
import json
d = json.load(open('${STATS_BODY}'))
for k in ('today_count','streak_days','total_completed'):
    assert k in d and isinstance(d[k], int) and d[k] >= 0, f'bad stats key {k}: {d}'
"
rm -f "${STATS_BODY}"

echo "PASS: S209 -- pill backend contract (active/start/pause/resume/abandon/stats) exercised (session=${SESSION_ID})"
