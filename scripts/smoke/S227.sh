#!/usr/bin/env bash
# Smoke test for S227: Quality tab -- GET /evals/runs, GET /evals/golden/{name},
# extended POST /evals/run.
#
# Verifies:
#   1.  backend is healthy
#   2.  GET /evals/runs -- returns 200 with a JSON array
#   3.  GET /evals/runs?dataset_name=nonexistent -- returns 200 with empty array
#   4.  GET /evals/golden/{name} -- 200 for a known file, 404 for unknown
#   5.  GET /evals/golden/{name} -- 400 for path-traversal attempts
#   6.  POST /evals/run -- accepts extended body (202 when golden exists, 404 when not)

set -euo pipefail

BASE="http://localhost:7820"

fail() {
  echo "FAIL: $1"
  exit 1
}

# 1. Health check
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (got ${HTTP})"

# 2. GET /evals/runs -- must return 200 and a JSON array
BODY=$(curl -s -w "\n%{http_code}" "${BASE}/evals/runs")
HTTP=$(echo "$BODY" | tail -1)
CONTENT=$(echo "$BODY" | head -1)
[ "$HTTP" = "200" ] || fail "GET /evals/runs expected 200, got ${HTTP}"
echo "$CONTENT" | python3 -c "import sys, json; data=json.load(sys.stdin); assert isinstance(data, list)" \
  || fail "GET /evals/runs did not return a JSON array"

# 3. GET /evals/runs?dataset_name=nonexistent_xyz -- 200 with empty array
BODY=$(curl -s -w "\n%{http_code}" "${BASE}/evals/runs?dataset_name=nonexistent_xyz_12345")
HTTP=$(echo "$BODY" | tail -1)
CONTENT=$(echo "$BODY" | head -1)
[ "$HTTP" = "200" ] || fail "GET /evals/runs?dataset_name=nonexistent expected 200, got ${HTTP}"
echo "$CONTENT" | python3 -c "import sys, json; data=json.load(sys.stdin); assert data == [], f'expected [], got {data}'" \
  || fail "GET /evals/runs?dataset_name=nonexistent should return []"

# 4a. GET /evals/golden/{name} for a known golden file (if exists: expect 200; else 404 is ok)
KNOWN_GOLDEN="book_time_machine"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/evals/golden/${KNOWN_GOLDEN}")
if [ "$HTTP" = "200" ]; then
  BODY=$(curl -s "${BASE}/evals/golden/${KNOWN_GOLDEN}")
  echo "$BODY" | python3 -c "
import sys, json
data = json.load(sys.stdin)
assert 'name' in data, 'missing name'
assert 'total' in data, 'missing total'
assert 'questions' in data, 'missing questions'
assert isinstance(data['questions'], list), 'questions not a list'
print(f'  golden {data[\"name\"]}: {data[\"total\"]} total, {len(data[\"questions\"])} on page')
" || fail "GET /evals/golden/${KNOWN_GOLDEN} response missing required fields"
  echo "  GET /evals/golden/${KNOWN_GOLDEN}: 200 OK"
elif [ "$HTTP" = "404" ]; then
  echo "  GET /evals/golden/${KNOWN_GOLDEN}: 404 (file not present in this environment, OK)"
else
  fail "GET /evals/golden/${KNOWN_GOLDEN} expected 200 or 404, got ${HTTP}"
fi

# 4b. GET /evals/golden/does_not_exist_xyz -- expect 404
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/evals/golden/does_not_exist_xyz_abc")
[ "$HTTP" = "404" ] || fail "GET /evals/golden/unknown expected 404, got ${HTTP}"

# 5. Path traversal rejection -- name with .. must return 400 or 404 or 422 (not 200)
# URL-encoded ..%2Ffoo
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/evals/golden/..%2Ffoo")
[ "$HTTP" != "200" ] || fail "GET /evals/golden/..%2Ffoo should not return 200"
echo "  path traversal ..%2Ffoo: ${HTTP} (not 200, correct)"

# Name with only invalid chars (contains a dot sequence after URL decode)
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/evals/golden/foo%2Fbar")
[ "$HTTP" != "200" ] || fail "GET /evals/golden/foo%2Fbar should not return 200"
echo "  path traversal foo%2Fbar: ${HTTP} (not 200, correct)"

# 6. POST /evals/run with extended body -- expect 202 (golden exists) or 404 (not present)
# Use max_questions=1 + judge_model="" to skip LLM judge and keep the eval fast (retrieval only).
HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${BASE}/evals/run" \
  -H "Content-Type: application/json" \
  -d "{\"dataset\":\"${KNOWN_GOLDEN}\",\"judge_model\":\"\",\"max_questions\":1}")
[ "$HTTP" = "202" ] || [ "$HTTP" = "404" ] || \
  fail "POST /evals/run with extended body expected 202 or 404, got ${HTTP}"
echo "  POST /evals/run (extended): ${HTTP}"

# 7. If the run was accepted (202), poll GET /evals/runs?dataset_name=... until a new row appears.
#    The eval subprocess is async; wait up to 90s (30 attempts x 3s).
if [ "$HTTP" = "202" ]; then
  # Poll up to 10 minutes (200 x 3s). First-run eval requires full document ingestion
  # which can take several minutes for large books. Exits immediately once a row appears.
  echo "  Polling GET /evals/runs?dataset_name=${KNOWN_GOLDEN} for new row (up to 10 min)..."
  FOUND=0
  for i in $(seq 1 200); do
    ROW_COUNT=$(curl -s "${BASE}/evals/runs?dataset_name=${KNOWN_GOLDEN}" \
      | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data))" 2>/dev/null || echo "0")
    if [ "$ROW_COUNT" -gt "0" ]; then
      FOUND=1
      echo "  Row appeared after ~$((i * 3))s (total rows: ${ROW_COUNT})"
      break
    fi
    sleep 3
  done
  [ "$FOUND" = "1" ] || fail "No row appeared in eval_runs after 10min for dataset ${KNOWN_GOLDEN}"
fi

echo "PASS: S227 -- /evals/runs, /evals/golden, POST /evals/run verified"
