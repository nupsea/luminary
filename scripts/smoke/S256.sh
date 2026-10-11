#!/usr/bin/env bash
# Smoke test for S256: cloud provider setup in Settings, on the wire.
#
# What this guards: picking Google Gemini listed no models until a key was saved,
# and a bad key read as an empty list. Every provider now lists models before a
# key exists, and POST /settings/llm/key checks a key before keeping it.
#
# Verifies:
#   1. backend is healthy
#   2. each provider lists at least one model, each carrying `recommended`
#   3. a blank key is refused (422) before anything is sent to a provider
#
# Never posts a real-looking key: that would contact the provider, and an
# unreachable one keeps the key.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

FAIL=0

check() {
    local desc="$1" expected="$2" actual="$3"
    if [ "$actual" != "$expected" ]; then
        echo "FAIL: $desc (expected=$expected, actual=$actual)"
        FAIL=1
    else
        echo "PASS: $desc"
    fi
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/health")
check "backend healthy" "200" "$HTTP"

for PROVIDER in openai anthropic gemini; do
    OK=$(curl -sf "$BASE/settings/llm/models?provider=$PROVIDER" | python3 -c "
import json, sys
models = json.load(sys.stdin)
print(bool(models) and all('recommended' in m and m['id'] for m in models))")
    check "$PROVIDER lists models before a key is required" "True" "$OK"
done

HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" \
    -d '{"provider":"gemini","api_key":"   "}' "$BASE/settings/llm/key")
check "a blank key is refused" "422" "$HTTP"

exit $FAIL
