#!/usr/bin/env bash
# Run all smoke tests sequentially.
# Requires the backend to be running on localhost:8000.
# Exit 1 if any smoke test fails.

set -euo pipefail

SMOKE_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0
FAIL=0

echo "=== Luminary Smoke Tests ==="
echo "Backend: http://localhost:8000"
echo ""

for script in "$SMOKE_DIR"/S*.sh; do
  name="$(basename "$script")"
  if bash "$script"; then
    echo "  [PASS] $name"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $name"
    FAIL=$((FAIL + 1))
  fi
done

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
