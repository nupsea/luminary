#!/usr/bin/env bash
# Smoke test for S140: the code-execution sandbox stays removed.
#
# This script used to exercise `POST /code/execute` (predict-then-run). That
# endpoint ran user-supplied code without a sandbox and was deleted on purpose
# in 33748f2 ("enable security/async lint, close SQL injection, drop
# code_executor"). Repairing this script by restoring the endpoint would
# reintroduce the vulnerability, so it asserts the absence instead: a removal is
# only durable if something fails when it comes back.
#
# Verifies:
#   1. backend is healthy
#   2. POST /code/execute is not served
#   3. no route under /code/ appears in the schema -- a rename would not count
#      as still-removed
#
# Requires a running backend at localhost:7820.
# smoke-expects-absent: /code/execute
set -euo pipefail

BASE="${BASE:-http://localhost:7820}"

fail() {
  echo "FAIL: $1"
  exit 1
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (HTTP $HTTP)"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/code/execute" \
  -H 'Content-Type: application/json' \
  -d '{"code":"print(1)","language":"python"}')
case "$HTTP" in
  404|405)
    echo "  POST /code/execute is not served (HTTP $HTTP)" ;;
  *)
    fail "an unsandboxed code executor answers on /code/execute (HTTP $HTTP)" ;;
esac

curl -s "${BASE}/openapi.json" | python3 -c "
import sys, json
paths = json.load(sys.stdin)['paths']
served = [p for p in paths if p.startswith('/code/') or p == '/code']
assert not served, f'code execution is back under {served}'
print('  no /code route in the schema')
" || fail "a code-execution route is registered"

echo "PASS: S140 -- the code execution sandbox is still removed"
