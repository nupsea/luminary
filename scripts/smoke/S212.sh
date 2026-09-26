#!/usr/bin/env bash
# Smoke test for S212: retrieval golden baseline is healthy.
#
# Exits 0 iff:
#   1. Backend is healthy (200 on /health).
#   2. evals/audit_golden.py runs without error against the three book
#      datasets and reports no empty result sets.
#   3. run_eval.py --assert-thresholds passes relaxed S212 gates:
#      HR@5 >= 0.50 and MRR >= 0.35.
#
# Backend is expected on localhost:7820 (the project's dev port). The
# story's user-journey shows port 8000 as an example; the smoke uses the
# real dev port to match every other smoke in scripts/smoke/.

set -euo pipefail
source "$(dirname "$0")/lib.sh"
smoke_requires_repo_toolchain

# Its manifest and history describe this server, not the developer's library.
export LUMINARY_EVAL_STATE_DIR="$SMOKE_TMP/eval-state"
mkdir -p "$LUMINARY_EVAL_STATE_DIR"
# run_eval.py reads which rerank arm ships from /evals/environment, which public
# mode does not mount; without it the eval refuses rather than guess the arm.
# smoke-calls: /evals/environment
smoke_require_mode full

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EVALS_DIR="${REPO_ROOT}/evals"

# 0. Backend health
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
if [ "$HTTP_HEALTH" != "200" ]; then
  echo "FAIL: backend not healthy (got ${HTTP_HEALTH}). Start the backend, or set LUMINARY_BASE_URL."
  exit 1
fi

# 1. Run audit_golden.py against the three book datasets and capture JSON.
AUDIT_OUT=$(mktemp)
trap 'rm -f "${AUDIT_OUT}"' EXIT

cd "${EVALS_DIR}"

for ds in book_time_machine book_alice odyssey; do
  if uv run python audit_golden.py --dataset "${ds}" --backend-url "${BASE}" --quiet > "${AUDIT_OUT}" 2>&1; then
    :
  else
    echo "FAIL: audit_golden.py exited non-zero for ${ds}"
    cat "${AUDIT_OUT}"
    exit 1
  fi

  # The audit prints a JSON summary block at the end; extract it.
  EMPTY=$(python3 - "${AUDIT_OUT}" <<'PY'
import json, sys, re
out = open(sys.argv[1]).read()
# JSON summary follows the line "JSON summary:"
if "JSON summary:" not in out:
    print(-1); sys.exit(0)
blob = out.split("JSON summary:", 1)[1].strip()
data = json.loads(blob)
# An empty summary is "nothing was audited", which summed to zero empties and
# read as healthy. It is how `book_odyssey` -- a dataset with no golden file --
# passed this check for as long as the name has been wrong.
if not data:
    print(-1); sys.exit(0)
empties = sum(d.get("empty", 0) for d in data)
print(empties)
PY
)

  if [ "${EMPTY}" = "-1" ]; then
    echo "FAIL: audit of ${ds} reported nothing to score (missing golden, or unparseable output)"
    cat "${AUDIT_OUT}"
    exit 1
  fi

  if [ "${EMPTY}" != "0" ]; then
    echo "FAIL: ${ds} has ${EMPTY} 'empty' entries (no chunks returned by /search)."
    echo "      Manifest is likely stale or books are not ingested. Audit detail:"
    cat "${AUDIT_OUT}"
    exit 1
  fi

  echo "OK:   ${ds} audit -- 0 empty entries (manifest live, /search responsive)"

  if uv run python run_eval.py --dataset "${ds}" --backend-url "${BASE}" --assert-thresholds > "${AUDIT_OUT}" 2>&1; then
    echo "OK:   ${ds} eval -- relaxed thresholds passed"
  else
    echo "FAIL: ${ds} failed relaxed S212 eval thresholds"
    cat "${AUDIT_OUT}"
    exit 1
  fi
done

echo "PASS: S212 -- retrieval golden baseline clears relaxed book thresholds"
