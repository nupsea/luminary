#!/usr/bin/env bash
# Run all smoke tests sequentially against LUMINARY_BASE_URL (see lib.sh).
# Exit 1 if any smoke test fails. A skip -- a script for a surface this server's
# mode does not mount -- is reported and counted, never folded into the passes.

set -euo pipefail
source "$(dirname "$0")/lib.sh"

PASS=0
FAIL=0
SKIP=0
SKIPPED=()

# Recorded before anything runs so clean.sh has a window to delete within, and
# kept afterwards so `make smoke-clean` can still tidy up after a run that died
# partway. Fixture titles alone are not safe to match on -- see clean.sh.
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "$STARTED_AT" > "$SMOKE_DIR/.last-run"
trap 'rm -rf "$SMOKE_TMP"' EXIT

MODE="$(smoke_server_mode)"
if [ -z "$MODE" ]; then
  echo "No mode from $BASE/health. Start the backend, or set LUMINARY_BASE_URL."
  exit 1
fi

echo "=== Luminary Smoke Tests ==="
echo "Backend: $BASE ($MODE mode)"
echo ""

for script in "$SMOKE_DIR"/S*.sh; do
  name="$(basename "$script")"
  status=0
  bash "$script" || status=$?
  if [ "$status" -eq 0 ]; then
    echo "  [PASS] $name"
    PASS=$((PASS + 1))
  elif [ "$status" -eq "$SMOKE_SKIP" ]; then
    echo "  [SKIP] $name"
    SKIP=$((SKIP + 1))
    SKIPPED+=("${name%.sh}")
  else
    echo "  [FAIL] $name"
    FAIL=$((FAIL + 1))
  fi
done

echo ""
echo "Results: $PASS passed, $FAIL failed, $SKIP skipped ($MODE mode)"
if [ "$SKIP" -gt 0 ]; then
  echo "Skipped: ${SKIPPED[*]}"
fi

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
