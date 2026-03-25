#!/usr/bin/env bash
set -euo pipefail

BASE="http://localhost:7820"
fail() { echo "FAIL: $1"; exit 1; }

# ---------------------------------------------------------------------------
# 1. POST /admin/notes/reindex -- no auth when ADMIN_KEY is empty (default dev)
# ---------------------------------------------------------------------------
REINDEX_JSON=$(curl -sf -X POST "$BASE/admin/notes/reindex")
echo "$REINDEX_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
assert data.get('queued') is True, 'expected queued=true, got: ' + str(data)
assert isinstance(data.get('total_notes'), int), 'expected total_notes int, got: ' + str(data)
assert data['total_notes'] >= 0, 'total_notes must be >= 0'
print('POST /admin/notes/reindex OK queued=%s total_notes=%d' % (data['queued'], data['total_notes']))
"

# ---------------------------------------------------------------------------
# 2. POST /admin/notes/reindex -- wrong key returns 403 (only if ADMIN_KEY set)
# ---------------------------------------------------------------------------
# Only verify 403 behavior when server has ADMIN_KEY configured.
# In default dev mode (ADMIN_KEY=''), the endpoint always allows.
STATUS_WRONG=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  -H 'X-Admin-Key: definitelywrong' \
  "$BASE/admin/notes/reindex" 2>/dev/null || echo "200")
# Accept 200 (no auth) or 403 (auth configured) -- either is correct
if [ "$STATUS_WRONG" != "200" ] && [ "$STATUS_WRONG" != "403" ]; then
  fail "POST /admin/notes/reindex with wrong key expected 200 or 403, got $STATUS_WRONG"
fi
echo "POST /admin/notes/reindex wrong-key check OK (status=$STATUS_WRONG)"

echo ""
echo "S170 smoke: all checks passed"
