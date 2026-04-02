#!/usr/bin/env bash
# Smoke test for S199: Naming conventions
# Tests: collection normalization, tag normalization, autocomplete normalization,
#        migration endpoints
set -euo pipefail

BASE="${LUMINARY_URL:-http://localhost:8000}"
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

# 1. POST /collections normalizes name
TMPFILE=$(mktemp /tmp/s199_XXXXXX)
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
    -X POST "$BASE/collections" \
    -H "Content-Type: application/json" \
    -d '{"name": "my reading notes", "color": "#6366F1"}')
check "POST /collections status" "201" "$HTTP"
COL_NAME=$(python3 -c "import json; print(json.load(open('$TMPFILE'))['name'])")
check "Collection name normalized" "MY-READING-NOTES" "$COL_NAME"
COL_ID=$(python3 -c "import json; print(json.load(open('$TMPFILE'))['id'])")

# 2. POST /tags normalizes id
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
    -X POST "$BASE/tags" \
    -H "Content-Type: application/json" \
    -d '{"id": "Science/Cell_Division", "display_name": "Cell Division"}')
check "POST /tags status" "201" "$HTTP"
TAG_ID=$(python3 -c "import json; print(json.load(open('$TMPFILE'))['id'])")
check "Tag id normalized" "science/cell-division" "$TAG_ID"

# 3. GET /tags/autocomplete normalizes query
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
    "$BASE/tags/autocomplete?q=Science%2FCell")
check "GET /tags/autocomplete status" "200" "$HTTP"

# 4. POST /tags/migrate-naming
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
    -X POST "$BASE/tags/migrate-naming")
check "POST /tags/migrate-naming status" "200" "$HTTP"

# 5. POST /collections/migrate-naming
HTTP=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
    -X POST "$BASE/collections/migrate-naming")
check "POST /collections/migrate-naming status" "200" "$HTTP"

# Cleanup: delete the test collection
curl -s -o /dev/null -X DELETE "$BASE/collections/$COL_ID"

rm -f "$TMPFILE"

if [ "$FAIL" -ne 0 ]; then
    echo "SMOKE FAILED"
    exit 1
fi
echo "ALL SMOKE TESTS PASSED"
exit 0
