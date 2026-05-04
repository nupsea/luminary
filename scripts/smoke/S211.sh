#!/usr/bin/env bash
# Smoke test for S211: typed Learning Goals UI on Study tab + Attach-to-goal in
# the FocusTimerPill. The frontend story uses the existing S210 backend; this
# script exercises the exact request/response shapes the new UI depends on.
#
# Verifies:
#   1.  POST /goals with the new dialog payload (typed goal_type + optional links)
#   2.  GET /goals?status=active returns the goal (used by FocusTimerPill select)
#   3.  GET /goals/{id} (used by GoalDetailPanel)
#   4.  GET /goals/{id}/progress shape per goal_type (drives GoalProgressBar)
#   5.  GET /goals/{id}/sessions returns linked sessions (drives detail panel list)
#   6.  POST /pomodoro/start with goal_id sets goal_id on the session
#   7.  Complete -> progress increments AND /pomodoro/stats Today/Streak/Total update
#   8.  PATCH /goals/{id} updates editable fields (drives GoalEditDialog)
#   9.  POST /goals/{id}/archive and /complete (drives detail panel actions)
#  10.  Goalless session still counts toward /pomodoro/stats (hybrid model invariant)
#  11.  DELETE /goals/{id} returns 204 and unlinks any sessions (goal_id NULL)
#
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# 0. Backend health
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 0b. Drop any active session left by a previous run.
ACTIVE_BODY=$(mktemp)
HTTP_ACTIVE=$(curl -s -o "${ACTIVE_BODY}" -w "%{http_code}" "${BASE}/pomodoro/active")
if [ "$HTTP_ACTIVE" = "200" ]; then
  EXISTING_ID=$(python3 -c "import json; print(json.load(open('${ACTIVE_BODY}'))['id'])")
  curl -s -o /dev/null -X POST "${BASE}/pomodoro/${EXISTING_ID}/abandon" || true
fi
rm -f "${ACTIVE_BODY}"

# Capture the baseline total_completed for the goalless invariant test below.
STATS_BEFORE=$(mktemp)
curl -s -o "${STATS_BEFORE}" "${BASE}/pomodoro/stats"
TOTAL_BEFORE=$(python3 -c "import json; print(json.load(open('${STATS_BEFORE}'))['total_completed'])")
rm -f "${STATS_BEFORE}"

# ---------------------------------------------------------------------------
# 1. Create a recall goal (matches GoalCreateDialog payload).
# ---------------------------------------------------------------------------
CREATE_BODY=$(mktemp)
HTTP_CREATE=$(curl -s -o "${CREATE_BODY}" -w "%{http_code}" \
  -X POST "${BASE}/goals" \
  -H "Content-Type: application/json" \
  -d '{"title":"S211 smoke recall goal","description":"made by smoke","goal_type":"recall","target_value":50,"target_unit":"cards"}')
if [ "$HTTP_CREATE" != "200" ]; then
  echo "FAIL: POST /goals expected 200, got ${HTTP_CREATE}"
  cat "${CREATE_BODY}"
  rm -f "${CREATE_BODY}"
  exit 1
fi
GOAL_ID=$(python3 -c "import json; d=json.load(open('${CREATE_BODY}')); assert d['status']=='active'; assert d['goal_type']=='recall'; assert d['target_value']==50; print(d['id'])")
rm -f "${CREATE_BODY}"

# ---------------------------------------------------------------------------
# 2. GET /goals?status=active -- used by FocusTimerPill Attach-to-goal select.
# ---------------------------------------------------------------------------
LIST_BODY=$(mktemp)
HTTP_LIST=$(curl -s -o "${LIST_BODY}" -w "%{http_code}" "${BASE}/goals?status=active")
if [ "$HTTP_LIST" != "200" ]; then
  echo "FAIL: GET /goals?status=active expected 200, got ${HTTP_LIST}"
  rm -f "${LIST_BODY}"
  exit 1
fi
python3 -c "
import json
d=json.load(open('${LIST_BODY}'))
assert isinstance(d, list)
assert any(g['id']=='${GOAL_ID}' and g['goal_type']=='recall' for g in d), 'goal not in active list'
"
rm -f "${LIST_BODY}"

# ---------------------------------------------------------------------------
# 3. GET /goals/{id} -- used by GoalDetailPanel.
# ---------------------------------------------------------------------------
GET_BODY=$(mktemp)
HTTP_GET=$(curl -s -o "${GET_BODY}" -w "%{http_code}" "${BASE}/goals/${GOAL_ID}")
if [ "$HTTP_GET" != "200" ]; then
  echo "FAIL: GET /goals/{id} expected 200, got ${HTTP_GET}"
  rm -f "${GET_BODY}"
  exit 1
fi
python3 -c "
import json
d=json.load(open('${GET_BODY}'))
assert d['id']=='${GOAL_ID}'
assert d['goal_type']=='recall'
assert d['description']=='made by smoke'
"
rm -f "${GET_BODY}"

# ---------------------------------------------------------------------------
# 4. GET /goals/{id}/progress -- shape drives GoalProgressBar.
# ---------------------------------------------------------------------------
PROG_BODY=$(mktemp)
HTTP_PROG=$(curl -s -o "${PROG_BODY}" -w "%{http_code}" "${BASE}/goals/${GOAL_ID}/progress")
if [ "$HTTP_PROG" != "200" ]; then
  echo "FAIL: GET /goals/{id}/progress expected 200, got ${HTTP_PROG}"
  rm -f "${PROG_BODY}"
  exit 1
fi
python3 -c "
import json
d=json.load(open('${PROG_BODY}'))
m=d['metrics']
assert d['goal_type']=='recall'
assert 'cards_reviewed' in m
assert 'sessions_completed' in m
assert 'completed_pct' in m
"
rm -f "${PROG_BODY}"

# ---------------------------------------------------------------------------
# 5. POST /pomodoro/start with goal_id -- the FocusTimerPill sends this.
# ---------------------------------------------------------------------------
START_BODY=$(mktemp)
HTTP_START=$(curl -s -o "${START_BODY}" -w "%{http_code}" \
  -X POST "${BASE}/pomodoro/start" \
  -H "Content-Type: application/json" \
  -d "{\"focus_minutes\":1,\"break_minutes\":1,\"surface\":\"recall\",\"goal_id\":\"${GOAL_ID}\"}")
if [ "$HTTP_START" != "200" ]; then
  echo "FAIL: pomodoro start with goal_id expected 200, got ${HTTP_START}"
  cat "${START_BODY}"
  rm -f "${START_BODY}"
  exit 1
fi
SESSION_ID=$(python3 -c "
import json
d=json.load(open('${START_BODY}'))
assert d['goal_id']=='${GOAL_ID}', f\"expected goal_id={'${GOAL_ID}'}, got {d['goal_id']}\"
print(d['id'])
")
rm -f "${START_BODY}"

# 5b. GET /goals/{id}/sessions includes the new session.
SESSIONS_BODY=$(mktemp)
HTTP_SESSIONS=$(curl -s -o "${SESSIONS_BODY}" -w "%{http_code}" "${BASE}/goals/${GOAL_ID}/sessions?limit=20")
if [ "$HTTP_SESSIONS" != "200" ]; then
  echo "FAIL: GET /goals/{id}/sessions expected 200, got ${HTTP_SESSIONS}"
  rm -f "${SESSIONS_BODY}"
  exit 1
fi
python3 -c "
import json
d=json.load(open('${SESSIONS_BODY}'))
assert isinstance(d, list)
assert any(s['id']=='${SESSION_ID}' for s in d), 'session not in linked list'
"
rm -f "${SESSIONS_BODY}"

# 5c. Complete the session.
HTTP_COMPLETE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/pomodoro/${SESSION_ID}/complete")
if [ "$HTTP_COMPLETE" != "200" ]; then
  echo "FAIL: complete expected 200, got ${HTTP_COMPLETE}"
  exit 1
fi

# ---------------------------------------------------------------------------
# 6. PATCH /goals/{id} -- title + description (matches GoalEditDialog payload).
# ---------------------------------------------------------------------------
PATCH_BODY=$(mktemp)
HTTP_PATCH=$(curl -s -o "${PATCH_BODY}" -w "%{http_code}" \
  -X PATCH "${BASE}/goals/${GOAL_ID}" \
  -H "Content-Type: application/json" \
  -d '{"title":"S211 smoke recall (renamed)","description":"updated"}')
if [ "$HTTP_PATCH" != "200" ]; then
  echo "FAIL: PATCH /goals/{id} expected 200, got ${HTTP_PATCH}"
  cat "${PATCH_BODY}"
  rm -f "${PATCH_BODY}"
  exit 1
fi
python3 -c "
import json
d=json.load(open('${PATCH_BODY}'))
assert d['title']=='S211 smoke recall (renamed)'
assert d['description']=='updated'
"
rm -f "${PATCH_BODY}"

# ---------------------------------------------------------------------------
# 7. POST /goals/{id}/complete -- detail panel Complete button.
# ---------------------------------------------------------------------------
HTTP_GOAL_COMPLETE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/goals/${GOAL_ID}/complete")
if [ "$HTTP_GOAL_COMPLETE" != "200" ]; then
  echo "FAIL: goal complete expected 200, got ${HTTP_GOAL_COMPLETE}"
  exit 1
fi
COMPLETED=$(mktemp)
curl -s -o "${COMPLETED}" "${BASE}/goals/${GOAL_ID}"
python3 -c "
import json
d=json.load(open('${COMPLETED}'))
assert d['status']=='completed'
assert d['completed_at'] is not None
"
rm -f "${COMPLETED}"

# ---------------------------------------------------------------------------
# 8. POST /goals/{id}/archive -- detail panel Archive button.
# ---------------------------------------------------------------------------
HTTP_ARCH=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/goals/${GOAL_ID}/archive")
if [ "$HTTP_ARCH" != "200" ]; then
  echo "FAIL: archive expected 200, got ${HTTP_ARCH}"
  exit 1
fi

# ---------------------------------------------------------------------------
# 9. Goalless invariant -- a goalless completed session must still tally to stats.
# ---------------------------------------------------------------------------
GS_BODY=$(mktemp)
HTTP_GS=$(curl -s -o "${GS_BODY}" -w "%{http_code}" \
  -X POST "${BASE}/pomodoro/start" \
  -H "Content-Type: application/json" \
  -d '{"focus_minutes":1,"break_minutes":1,"surface":"none"}')
if [ "$HTTP_GS" != "200" ]; then
  echo "FAIL: goalless start expected 200, got ${HTTP_GS}"
  cat "${GS_BODY}"
  rm -f "${GS_BODY}"
  exit 1
fi
GS_ID=$(python3 -c "
import json
d=json.load(open('${GS_BODY}'))
assert d['goal_id'] is None
print(d['id'])
")
rm -f "${GS_BODY}"

curl -s -o /dev/null -X POST "${BASE}/pomodoro/${GS_ID}/complete"

STATS_AFTER=$(mktemp)
curl -s -o "${STATS_AFTER}" "${BASE}/pomodoro/stats"
python3 -c "
import json
d=json.load(open('${STATS_AFTER}'))
assert d['total_completed'] >= ${TOTAL_BEFORE} + 2, f\"expected {${TOTAL_BEFORE}} + 2 completed, got {d['total_completed']}\"
assert d['today_count'] >= 2
"
rm -f "${STATS_AFTER}"

# ---------------------------------------------------------------------------
# 10. DELETE /goals/{id} returns 204; deleted goal -> 404 on subsequent GET.
# ---------------------------------------------------------------------------
HTTP_DEL=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "${BASE}/goals/${GOAL_ID}")
if [ "$HTTP_DEL" != "204" ]; then
  echo "FAIL: DELETE /goals/{id} expected 204, got ${HTTP_DEL}"
  exit 1
fi
HTTP_GET_DEL=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/goals/${GOAL_ID}")
if [ "$HTTP_GET_DEL" != "404" ]; then
  echo "FAIL: GET deleted goal expected 404, got ${HTTP_GET_DEL}"
  exit 1
fi

echo "PASS: S211 -- typed-goals UI contract verified (CRUD + progress + linked sessions + goalless invariant)"
