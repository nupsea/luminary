#!/usr/bin/env bash
# dev-logs.sh — start backend and frontend with colorized, prefixed output.
# Backend lines: cyan [BACKEND]; frontend lines: green [FRONTEND].
# Ctrl-C cleanly stops both child processes.
#
# Requirements: bash, awk, uv, npm — all available on macOS without extra installs.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Start backend with DEBUG logging; prefix each line with cyan [BACKEND]
(cd "$REPO_ROOT/backend" && LOG_LEVEL=DEBUG uv run uvicorn app.main:app --reload --port 7820 2>&1) \
    | awk 'BEGIN{p="\033[0;36m[BACKEND]\033[0m "}{print p $0; fflush()}' &
BACKEND_PID=$!

# Start frontend; prefix each line with green [FRONTEND]
(cd "$REPO_ROOT/frontend" && npm run dev 2>&1) \
    | awk 'BEGIN{p="\033[0;32m[FRONTEND]\033[0m "}{print p $0; fflush()}' &
FRONTEND_PID=$!

# Forward SIGINT/TERM to both children and wait for clean shutdown
_stop() {
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    exit 0
}
trap _stop INT TERM

wait "$BACKEND_PID" "$FRONTEND_PID"
