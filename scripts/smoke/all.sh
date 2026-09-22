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

# A hang detector, not a latency bound: without it one stream that never closes
# stalls the whole run with no verdict.
SCRIPT_TIMEOUT="${SMOKE_SCRIPT_TIMEOUT:-1800}"
SMOKE_TIMED_OUT=124

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

# run_capped <script>: its exit status, or SMOKE_TIMED_OUT once SCRIPT_TIMEOUT
# passes. Job control gives the script its own process group, so the kill takes
# its curl and python children with it.
run_capped() {
  local flag="$SMOKE_TMP/.timed-out" pid dog status=0
  rm -f "$flag"
  set -m
  bash "$1" < /dev/null &
  pid=$!
  ( sleep "$SCRIPT_TIMEOUT"; touch "$flag"; kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" ) &
  dog=$!
  set +m
  wait "$pid" || status=$?
  kill -TERM -- "-$dog" 2>/dev/null || kill -TERM "$dog" 2>/dev/null || true
  wait "$dog" 2>/dev/null || true
  if [ -f "$flag" ]; then
    status=$SMOKE_TIMED_OUT
  fi
  return "$status"
}

echo "=== Luminary Smoke Tests ==="
echo "Backend: $BASE ($MODE mode)"
echo ""

for script in "$SMOKE_DIR"/S*.sh; do
  name="$(basename "$script")"
  status=0
  run_capped "$script" || status=$?
  if [ "$status" -eq 0 ]; then
    echo "  [PASS] $name"
    PASS=$((PASS + 1))
  elif [ "$status" -eq "$SMOKE_SKIP" ]; then
    echo "  [SKIP] $name"
    SKIP=$((SKIP + 1))
    SKIPPED+=("${name%.sh}")
  elif [ "$status" -eq "$SMOKE_TIMED_OUT" ]; then
    echo "  [FAIL] $name (no verdict after ${SCRIPT_TIMEOUT}s; killed)"
    FAIL=$((FAIL + 1))
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
