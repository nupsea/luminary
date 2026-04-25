#!/usr/bin/env bash
# Smoke test for S210: typed Learning Goals backend.
# Verifies create -> list -> get -> patch -> archive -> complete -> link/unlink session
# -> progress -> delete (with goal_id NULL on linked session) -> goalless stats invariant.
# Requires the backend to be running on localhost:7820.

set -euo pipefail

BASE="http://localhost:7820"

# 1. Health
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH})"
  exit 1
fi

# 2. Clear any stale active pomodoro session from a previous run.
ACTIVE_BODY=$(mktemp)
HTTP_ACTIVE=$(curl -s -o "${ACTIVE_BODY}" -w "%{http_code}" "${BASE}/pomodoro/active")
if [ "$HTTP_ACTIVE" = "200" ]; then
  EXISTING_ID=$(python3 -c "import json; print(json.load(open('${ACTIVE_BODY}'))['id'])")
  curl -s -o /dev/null -X POST "${BASE}/pomodoro/${EXISTING_ID}/abandon" || true
fi
rm -f "${ACTIVE_BODY}"

# 3. POST /goals -- create a recall goal
CREATE_BODY=$(mktemp)
HTTP_CREATE=$(curl -s -o "${CREATE_BODY}" -w "%{http_code}" \
  -X POST "${BASE}/goals" \
  -H "Content-Type: application/json" \
  -d '{"title":"Smoke recall goal","goal_type":"recall","target_value":50,"target_unit":"cards","deck_id":"smoke-deck"}')
if [ "$HTTP_CREATE" != "200" ]; then
  echo "FAIL: POST /goals expected 200, got ${HTTP_CREATE}"
  cat "${CREATE_BODY}"
  rm -f "${CREATE_BODY}"
  exit 1
fi
GOAL_ID=$(python3 -c "import json; d=json.load(open('${CREATE_BODY}')); assert d['status']=='active'; assert d['goal_type']=='recall'; assert d['target_value']==50; print(d['id'])")
rm -f "${CREATE_BODY}"

if [ -z "${GOAL_ID}" ]; then
  echo "FAIL: missing id on POST /goals"
  exit 1
fi

# 4. GET /goals?status=active -- ensure the new goal appears
LIST_BODY=$(mktemp)
HTTP_LIST=$(curl -s -o "${LIST_BODY}" -w "%{http_code}" "${BASE}/goals?status=active")
if [ "$HTTP_LIST" != "200" ]; then
  echo "FAIL: GET /goals?status=active expected 200, got ${HTTP_LIST}"
  rm -f "${LIST_BODY}"
  exit 1
fi
python3 -c "import json; d=json.load(open('${LIST_BODY}')); assert any(g['id']=='${GOAL_ID}' for g in d), 'goal not in list'"
rm -f "${LIST_BODY}"

# 5. GET /goals/{id}
GET_BODY=$(mktemp)
HTTP_GET=$(curl -s -o "${GET_BODY}" -w "%{http_code}" "${BASE}/goals/${GOAL_ID}")
if [ "$HTTP_GET" != "200" ]; then
  echo "FAIL: GET /goals/{id} expected 200, got ${HTTP_GET}"
  rm -f "${GET_BODY}"
  exit 1
fi
python3 -c "import json; d=json.load(open('${GET_BODY}')); assert d['id']=='${GOAL_ID}'; assert d['goal_type']=='recall'"
rm -f "${GET_BODY}"

# 6. PATCH /goals/{id} -- update title only
PATCH_BODY=$(mktemp)
HTTP_PATCH=$(curl -s -o "${PATCH_BODY}" -w "%{http_code}" \
  -X PATCH "${BASE}/goals/${GOAL_ID}" \
  -H "Content-Type: application/json" \
  -d '{"title":"Smoke recall goal (renamed)"}')
if [ "$HTTP_PATCH" != "200" ]; then
  echo "FAIL: PATCH /goals/{id} expected 200, got ${HTTP_PATCH}"
  cat "${PATCH_BODY}"
  rm -f "${PATCH_BODY}"
  exit 1
fi
python3 -c "import json; d=json.load(open('${PATCH_BODY}')); assert d['title']=='Smoke recall goal (renamed)'; assert d['goal_type']=='recall'"
rm -f "${PATCH_BODY}"

# 7. GET /goals/{id}/progress -- recall shape
PROG_BODY=$(mktemp)
HTTP_PROG=$(curl -s -o "${PROG_BODY}" -w "%{http_code}" "${BASE}/goals/${GOAL_ID}/progress")
if [ "$HTTP_PROG" != "200" ]; then
  echo "FAIL: GET /goals/{id}/progress expected 200, got ${HTTP_PROG}"
  rm -f "${PROG_BODY}"
  exit 1
fi
python3 -c "import json; d=json.load(open('${PROG_BODY}')); m=d['metrics']; assert d['goal_type']=='recall'; assert 'cards_reviewed' in m; assert 'avg_retention' in m; assert 'sessions_completed' in m"
rm -f "${PROG_BODY}"

# 8. POST /goals/{id}/archive
HTTP_ARCH=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/goals/${GOAL_ID}/archive")
if [ "$HTTP_ARCH" != "200" ]; then
  echo "FAIL: archive expected 200, got ${HTTP_ARCH}"
  exit 1
fi
ARCH_GET=$(mktemp)
curl -s -o "${ARCH_GET}" "${BASE}/goals/${GOAL_ID}"
python3 -c "import json; d=json.load(open('${ARCH_GET}')); assert d['status']=='archived'"
rm -f "${ARCH_GET}"

# 9. Create a second goal of type read for link/unlink + delete-cleanup tests
CREATE2_BODY=$(mktemp)
HTTP_CREATE2=$(curl -s -o "${CREATE2_BODY}" -w "%{http_code}" \
  -X POST "${BASE}/goals" \
  -H "Content-Type: application/json" \
  -d '{"title":"Smoke read goal","goal_type":"read","target_value":60,"target_unit":"minutes"}')
if [ "$HTTP_CREATE2" != "200" ]; then
  echo "FAIL: second create expected 200, got ${HTTP_CREATE2}"
  cat "${CREATE2_BODY}"
  rm -f "${CREATE2_BODY}"
  exit 1
fi
GOAL2_ID=$(python3 -c "import json; print(json.load(open('${CREATE2_BODY}'))['id'])")
rm -f "${CREATE2_BODY}"

# 10. Start a pomodoro session and link it to GOAL2_ID
START_BODY=$(mktemp)
HTTP_START=$(curl -s -o "${START_BODY}" -w "%{http_code}" \
  -X POST "${BASE}/pomodoro/start" \
  -H "Content-Type: application/json" \
  -d '{"surface":"read"}')
if [ "$HTTP_START" != "200" ]; then
  echo "FAIL: pomodoro start expected 200, got ${HTTP_START}"
  cat "${START_BODY}"
  rm -f "${START_BODY}"
  exit 1
fi
SESSION_ID=$(python3 -c "import json; print(json.load(open('${START_BODY}'))['id'])")
rm -f "${START_BODY}"

HTTP_LINK=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/goals/${GOAL2_ID}/sessions/${SESSION_ID}")
if [ "$HTTP_LINK" != "200" ]; then
  echo "FAIL: link expected 200, got ${HTTP_LINK}"
  exit 1
fi

# Verify the link took effect via /pomodoro/active
LINKED_ACTIVE=$(mktemp)
curl -s -o "${LINKED_ACTIVE}" "${BASE}/pomodoro/active"
python3 -c "import json; d=json.load(open('${LINKED_ACTIVE}')); assert d['goal_id']=='${GOAL2_ID}'"
rm -f "${LINKED_ACTIVE}"

# 11. DELETE link
HTTP_UNLINK=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "${BASE}/goals/${GOAL2_ID}/sessions/${SESSION_ID}")
if [ "$HTTP_UNLINK" != "200" ]; then
  echo "FAIL: unlink expected 200, got ${HTTP_UNLINK}"
  exit 1
fi

# 12. Re-link, then delete the goal -- session should persist with goal_id NULL
curl -s -o /dev/null -X POST "${BASE}/goals/${GOAL2_ID}/sessions/${SESSION_ID}"
HTTP_DEL=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "${BASE}/goals/${GOAL2_ID}")
if [ "$HTTP_DEL" != "204" ]; then
  echo "FAIL: DELETE /goals/{id} expected 204, got ${HTTP_DEL}"
  exit 1
fi

POST_DEL=$(mktemp)
curl -s -o "${POST_DEL}" "${BASE}/pomodoro/active"
python3 -c "import json; d=json.load(open('${POST_DEL}')); assert d['id']=='${SESSION_ID}'; assert d['goal_id'] is None"
rm -f "${POST_DEL}"

HTTP_GET_DEL=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/goals/${GOAL2_ID}")
if [ "$HTTP_GET_DEL" != "404" ]; then
  echo "FAIL: GET deleted goal expected 404, got ${HTTP_GET_DEL}"
  exit 1
fi

# 13. Complete the (now-goalless) pomodoro session and verify /pomodoro/stats counts it
HTTP_COMPLETE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/pomodoro/${SESSION_ID}/complete")
if [ "$HTTP_COMPLETE" != "200" ]; then
  echo "FAIL: complete expected 200, got ${HTTP_COMPLETE}"
  exit 1
fi

STATS_BODY=$(mktemp)
HTTP_STATS=$(curl -s -o "${STATS_BODY}" -w "%{http_code}" "${BASE}/pomodoro/stats")
python3 -c "import json; d=json.load(open('${STATS_BODY}')); assert d['total_completed']>=1; assert d['today_count']>=1"
rm -f "${STATS_BODY}"

# 14. Final cleanup: delete the archived first goal
curl -s -o /dev/null -X DELETE "${BASE}/goals/${GOAL_ID}" || true

echo "PASS: S210 -- typed learning goals lifecycle, link/unlink, delete-cleanup, goalless stats invariant verified"
