#!/usr/bin/env bash
# Run all smoke tests sequentially.
# Requires the backend to be running on localhost:7820.
# Exit 1 if any smoke test fails.

set -euo pipefail

SMOKE_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0
FAIL=0

# Recorded before anything runs so clean.sh has a window to delete within, and
# kept afterwards so `make smoke-clean` can still tidy up after a run that died
# partway. Fixture titles alone are not safe to match on -- see clean.sh.
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "$STARTED_AT" > "$SMOKE_DIR/.last-run"

echo "=== Luminary Smoke Tests ==="
echo "Backend: http://localhost:7820"
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

# Always, including after failures: a run that fails partway still ingested
# whatever it got to, and leaving that behind is how 27 documents and 30 notes
# accumulated in a real library across eight runs.
if [ "${SMOKE_KEEP_FIXTURES:-0}" != "1" ]; then
  echo ""
  bash "$SMOKE_DIR/clean.sh" --since "$STARTED_AT" || echo "  (smoke-clean failed; run 'make smoke-clean' once the backend is up)"
fi

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
