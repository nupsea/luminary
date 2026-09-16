#!/usr/bin/env bash
# Run a command under a resident-memory ceiling and kill its whole process tree
# if it crosses. For local probes that load ML runtimes: an execution provider
# that recompiles per input shape grows without bound and wedges the host long
# before the OOM killer helps.
#
#   scripts/capped_run.sh uv run python probe/embed_speed.py out.json
#   MEM_CAP_GB=24 scripts/capped_run.sh make eval
#
# RSS undercounts memory-mapped model weights on unified memory, so this is a
# kill switch, not a measurement. Use scripts/mem_profile.py to measure.
set -uo pipefail

CAP_GB=${MEM_CAP_GB:-12}
POLL_S=${MEM_CAP_POLL_S:-2}
CAP_KB=$(awk -v g="$CAP_GB" 'BEGIN { printf "%d", g * 1048576 }')

if [ "$#" -eq 0 ]; then
  echo "usage: [MEM_CAP_GB=N] $0 <command> [args...]" >&2
  exit 64
fi

tree_rss_kb() {
  ps -Ao pid=,ppid=,rss= | awk -v root="$1" '
    { pid[NR] = $1; ppid[NR] = $2; rss[NR] = $3; n = NR }
    END {
      inset[root] = 1
      changed = 1
      while (changed) {
        changed = 0
        for (i = 1; i <= n; i++)
          if (!inset[pid[i]] && inset[ppid[i]]) { inset[pid[i]] = 1; changed = 1 }
      }
      total = 0
      for (i = 1; i <= n; i++) if (inset[pid[i]]) total += rss[i]
      print total
    }'
}

kill_tree() {
  local root=$1 sig=$2
  ps -Ao pid=,ppid= | awk -v root="$root" '
    { pid[NR] = $1; ppid[NR] = $2; n = NR }
    END {
      inset[root] = 1
      changed = 1
      while (changed) {
        changed = 0
        for (i = 1; i <= n; i++)
          if (!inset[pid[i]] && inset[ppid[i]]) { inset[pid[i]] = 1; changed = 1 }
      }
      for (i = 1; i <= n; i++) if (inset[pid[i]]) print pid[i]
    }' | xargs -r kill "-$sig" 2>/dev/null
}

"$@" &
child=$!
trap 'kill_tree "$child" TERM; exit 130' INT TERM

peak_kb=0
killed=0
while kill -0 "$child" 2>/dev/null; do
  used_kb=$(tree_rss_kb "$child")
  [ "$used_kb" -gt "$peak_kb" ] && peak_kb=$used_kb
  if [ "$used_kb" -gt "$CAP_KB" ]; then
    awk -v u="$used_kb" -v c="$CAP_GB" 'BEGIN {
      printf "capped_run: tree RSS %.1f GB over the %s GB cap; killing\n", u / 1048576, c }' >&2
    kill_tree "$child" TERM
    sleep 3
    kill_tree "$child" KILL
    killed=1
    break
  fi
  sleep "$POLL_S"
done

wait "$child"
status=$?
awk -v p="$peak_kb" 'BEGIN { printf "capped_run: peak tree RSS %.1f GB\n", p / 1048576 }' >&2
[ "$killed" -eq 1 ] && exit 137
exit "$status"
