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
TIMED_OUT=0

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

# What was still running when a script ran out of time, and in what state.
smoke_dump_group() {
  command -v pgrep >/dev/null 2>&1 || return 0
  local pids
  pids="$(pgrep -g "$1" | tr '\n' ',')"
  [ -n "$pids" ] && ps -o pid,stat,etime,command -p "${pids%,}" | cut -c1-200
}

# run_capped <script>: its exit status; sets TIMED_OUT=1 when the watchdog killed
# it. Job control gives the script its own process group, so the kill takes its
# curl and python children with it. The flag is per script, so a watchdog that
# fires late can never mark a different script.
run_capped() {
  local flag pid dog status=0
  TIMED_OUT=0
  set -m
  bash "$1" < /dev/null &
  pid=$!
  set +m
  flag="$SMOKE_TMP/.timed-out.$pid"
  # The trap takes the pending sleep with it: a watchdog outliving its script
  # would later fire at whatever reused that process group.
  (
    nap() { sleep "$1" & naps=$!; wait "$naps"; }
    trap 'kill "$naps" 2>/dev/null; exit 0' TERM
    nap "$SCRIPT_TIMEOUT"
    touch "$flag"
    smoke_dump_group "$pid" || true
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid"
    # bash defers TERM until its current child exits, then runs the next line.
    nap 5
    kill -KILL -- "-$pid" 2>/dev/null || true
  ) &
  dog=$!
  wait "$pid" || status=$?
  # Once it has fired, let the watchdog reach its KILL: the script can exit on
  # TERM and leave children behind in its group.
  [ -f "$flag" ] || kill -TERM "$dog" 2>/dev/null || true
  wait "$dog" 2>/dev/null || true
  if [ -f "$flag" ]; then
    TIMED_OUT=1
    rm -f "$flag"
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
  if [ "$TIMED_OUT" -eq 1 ]; then
    echo "  [FAIL] $name (no verdict after ${SCRIPT_TIMEOUT}s; killed)"
    FAIL=$((FAIL + 1))
  elif [ "$status" -eq 0 ]; then
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
