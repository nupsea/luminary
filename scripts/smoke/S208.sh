#!/usr/bin/env bash
# Smoke test for S208: Pomodoro session backend.
# Verifies start -> active -> pause -> resume -> complete flow plus stats and 409 invariants.
# Requires the backend to be running on localhost:7820.

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

# 3. POST /pomodoro/start with defaults
START_BODY=$(mktemp)
HTTP_START=$(curl -s -o "${START_BODY}" -w "%{http_code}" \
  -X POST "${BASE}/pomodoro/start" \
  -H "Content-Type: application/json" \
  -d '{}')
if [ "$HTTP_START" != "200" ]; then
  echo "FAIL: expected 200 for /pomodoro/start, got ${HTTP_START}"
  cat "${START_BODY}"
  rm -f "${START_BODY}"
  exit 1
fi

SESSION_ID=$(python3 -c "import json; d=json.load(open('${START_BODY}')); assert d['status']=='active'; assert d['focus_minutes']==25; assert d['break_minutes']==5; assert d['surface']=='none'; print(d['id'])")
rm -f "${START_BODY}"

if [ -z "${SESSION_ID}" ]; then
  echo "FAIL: missing id in /pomodoro/start response"
  exit 1
fi

# 4. Second start should 409 with existing_session_id
DUP_BODY=$(mktemp)
HTTP_DUP=$(curl -s -o "${DUP_BODY}" -w "%{http_code}" \
  -X POST "${BASE}/pomodoro/start" \
  -H "Content-Type: application/json" \
  -d '{}')
if [ "$HTTP_DUP" != "409" ]; then
  echo "FAIL: expected 409 on second /pomodoro/start, got ${HTTP_DUP}"
  cat "${DUP_BODY}"
  rm -f "${DUP_BODY}"
  exit 1
fi
python3 -c "import json; d=json.load(open('${DUP_BODY}'))['detail']; assert d['existing_session_id']=='${SESSION_ID}'"
rm -f "${DUP_BODY}"

# 5. GET /pomodoro/active returns the session
ACTIVE2=$(mktemp)
HTTP_ACT2=$(curl -s -o "${ACTIVE2}" -w "%{http_code}" "${BASE}/pomodoro/active")
if [ "$HTTP_ACT2" != "200" ]; then
  echo "FAIL: expected 200 on /pomodoro/active, got ${HTTP_ACT2}"
  rm -f "${ACTIVE2}"
  exit 1
fi
python3 -c "import json; d=json.load(open('${ACTIVE2}')); assert d['id']=='${SESSION_ID}'"
rm -f "${ACTIVE2}"

# 6. Pause -> Resume
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

# 7. Complete
COMPLETE_BODY=$(mktemp)
HTTP_DONE=$(curl -s -o "${COMPLETE_BODY}" -w "%{http_code}" -X POST "${BASE}/pomodoro/${SESSION_ID}/complete")
if [ "$HTTP_DONE" != "200" ]; then
  echo "FAIL: complete expected 200, got ${HTTP_DONE}"
  rm -f "${COMPLETE_BODY}"
  exit 1
fi
python3 -c "import json; d=json.load(open('${COMPLETE_BODY}')); assert d['status']=='completed'; assert d['completed_at'] is not None"
rm -f "${COMPLETE_BODY}"

# 8. Second complete -> 409
HTTP_DONE2=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/pomodoro/${SESSION_ID}/complete")
if [ "$HTTP_DONE2" != "409" ]; then
  echo "FAIL: double complete expected 409, got ${HTTP_DONE2}"
  exit 1
fi

# 9. GET /active is now 204
HTTP_ACT3=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/pomodoro/active")
if [ "$HTTP_ACT3" != "204" ]; then
  echo "FAIL: /pomodoro/active expected 204 after completion, got ${HTTP_ACT3}"
  exit 1
fi

# 10. GET /stats has the required keys with non-negative values
STATS_BODY=$(mktemp)
HTTP_STATS=$(curl -s -o "${STATS_BODY}" -w "%{http_code}" "${BASE}/pomodoro/stats")
if [ "$HTTP_STATS" != "200" ]; then
  echo "FAIL: stats expected 200, got ${HTTP_STATS}"
  rm -f "${STATS_BODY}"
  exit 1
fi
python3 -c "import json; d=json.load(open('${STATS_BODY}')); assert isinstance(d['today_count'], int); assert isinstance(d['streak_days'], int); assert isinstance(d['total_completed'], int); assert d['total_completed']>=1; assert d['today_count']>=1"
rm -f "${STATS_BODY}"

echo "PASS: S208 -- pomodoro start/pause/resume/complete/stats flow exercised (session=${SESSION_ID})"
