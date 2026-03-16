#!/usr/bin/env bash
# Smoke test for S113 - Learning Goals endpoints
# Requires: live backend at http://localhost:7820 and at least one ingested document.
set -euo pipefail

BASE="http://localhost:7820"

echo "=== S113 smoke: Learning Goals ==="

# 1. GET /goals -- should return list (possibly empty)
echo "[1] GET /goals"
GOALS=$(curl -sf "${BASE}/goals")
echo "    Response: ${GOALS}"
echo "${GOALS}" | python3 -c "import sys, json; d=json.load(sys.stdin); assert isinstance(d, list), 'expected list'"
echo "    PASS"

# 2. Get first document id
echo "[2] GET /documents to pick a doc_id"
FIRST_DOC=$(curl -sf "${BASE}/documents?sort=newest&page=1&page_size=1" | python3 -c "import sys, json; items=json.load(sys.stdin)['items']; print(items[0]['id']) if items else print('')")
if [ -z "${FIRST_DOC}" ]; then
    echo "    SKIP: no documents ingested -- skipping create/readiness checks"
    exit 0
fi
echo "    doc_id=${FIRST_DOC}"

# 3. POST /goals
echo "[3] POST /goals"
TARGET=$(python3 -c "from datetime import date, timedelta; print((date.today()+timedelta(days=30)).isoformat())")
CREATE_RESP=$(curl -sf -X POST "${BASE}/goals" \
    -H "Content-Type: application/json" \
    -d "{\"document_id\": \"${FIRST_DOC}\", \"title\": \"Smoke Test Goal\", \"target_date\": \"${TARGET}\"}")
echo "    Response: ${CREATE_RESP}"
GOAL_ID=$(echo "${CREATE_RESP}" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
echo "    goal_id=${GOAL_ID}"
echo "    PASS"

# 4. GET /goals/{id}/readiness
echo "[4] GET /goals/${GOAL_ID}/readiness"
READINESS=$(curl -sf "${BASE}/goals/${GOAL_ID}/readiness")
echo "    Response: ${READINESS}"
echo "${READINESS}" | python3 -c "
import sys, json
d=json.load(sys.stdin)
assert 'on_track' in d, 'missing on_track'
assert 'projected_retention_pct' in d, 'missing projected_retention_pct'
assert 'at_risk_card_count' in d, 'missing at_risk_card_count'
assert 'at_risk_cards' in d, 'missing at_risk_cards'
assert 0.0 <= d['projected_retention_pct'] <= 100.0, 'pct out of range'
"
echo "    PASS"

# 5. DELETE /goals/{id}
echo "[5] DELETE /goals/${GOAL_ID}"
DEL_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "${BASE}/goals/${GOAL_ID}")
[ "${DEL_STATUS}" = "204" ] || { echo "    FAIL: expected 204 got ${DEL_STATUS}"; exit 1; }
echo "    PASS"

echo "=== S113 smoke: ALL PASS ==="
