#!/usr/bin/env bash
# S254 smoke test: GET /settings/background returns both background-work switches as booleans
set -euo pipefail
source "$(dirname "$0")/lib.sh"

echo "S254: GET /settings/background returns 200..."
BODY=$(curl -s -w "\n%{http_code}" "${BASE}/settings/background")
STATUS=$(echo "$BODY" | tail -1)
RESPONSE=$(echo "$BODY" | head -1)

if [ "$STATUS" != "200" ]; then
  echo "FAIL: GET /settings/background returned $STATUS (expected 200)"
  exit 1
fi

for field in chapter_backfill quiet_background; do
  if ! echo "$RESPONSE" | grep -Eq "\"$field\":(true|false)"; then
    echo "FAIL: response missing boolean $field: $RESPONSE"
    exit 1
  fi
done

echo "PASS: GET /settings/background returned both switches"
