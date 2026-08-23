#!/usr/bin/env bash
# Smoke test for S113 - Learning Goals endpoints
#
# The document-centric goals API this script was written against was replaced by
# typed learning goals: `routers/goals.py` says so in its own module docstring,
# and `GET /goals/{id}/readiness` -- with its `on_track` /
# `projected_retention_pct` / `at_risk_cards` contract -- went with it. The
# router survives as a data source for the Hub, which is the live surface, so
# this covers that rather than the FSRS readiness projection.
#
# Verifies: list, create with the typed shape, read back, progress, delete.
# Requires: live backend at http://localhost:7820.
set -euo pipefail

BASE="${BASE:-http://localhost:7820}"

fail() { echo "    FAIL: $1"; exit 1; }

echo "=== S113 Smoke: Learning Goals ==="

# 1. GET /goals
echo "[1] GET /goals"
curl -sf "${BASE}/goals" | python3 -c "
import sys, json
rows = json.load(sys.stdin)
assert isinstance(rows, list), 'expected a list of goals'
" || fail "GET /goals did not return a list"
echo "    PASS"

# 2. POST /goals with the typed shape (title + goal_type, not document + date)
echo "[2] POST /goals"
CREATE_RESP=$(curl -sf -X POST "${BASE}/goals" \
  -H "Content-Type: application/json" \
  -d '{"title": "S113 Smoke Goal", "goal_type": "studying", "target_value": 30, "target_unit": "minutes"}')
GOAL_ID=$(echo "${CREATE_RESP}" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
[ -n "${GOAL_ID}" ] || fail "POST /goals returned no id"
echo "    goal_id=${GOAL_ID}"
echo "    PASS"

# 3. GET /goals/{id}
echo "[3] GET /goals/${GOAL_ID}"
curl -sf "${BASE}/goals/${GOAL_ID}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['title'] == 'S113 Smoke Goal', f\"title round-trip: {d['title']!r}\"
assert d['goal_type'] == 'studying', f\"goal_type: {d['goal_type']!r}\"
assert d['status'] == 'active', f\"a new goal starts active, got {d['status']!r}\"
" || fail "GET /goals/{id} did not round-trip the goal"
echo "    PASS"

# 4. GET /goals/{id}/progress -- what replaced the readiness projection.
#    `metrics` is typed per goal_type, so this asserts the envelope, not its keys.
echo "[4] GET /goals/${GOAL_ID}/progress"
curl -sf "${BASE}/goals/${GOAL_ID}/progress" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['goal_id'] == '${GOAL_ID}', 'progress reported for the wrong goal'
assert d['goal_type'] == 'studying', f\"goal_type: {d['goal_type']!r}\"
assert isinstance(d['metrics'], dict), 'metrics must be an object'
" || fail "GET /goals/{id}/progress did not report on this goal"
echo "    PASS"

# 5. DELETE /goals/{id} -- also keeps the library clean between runs.
echo "[5] DELETE /goals/${GOAL_ID}"
DEL_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "${BASE}/goals/${GOAL_ID}")
[ "${DEL_STATUS}" = "204" ] || fail "expected 204 got ${DEL_STATUS}"
echo "    PASS"

echo "=== S113 smoke: ALL PASS ==="
