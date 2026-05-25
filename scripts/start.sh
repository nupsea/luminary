#!/usr/bin/env bash
# start.sh — launch the production build: SPA + API on one port (7820), no reload.
# The frontend must be built first (`make build`). Polls /health, prints a ready
# banner with the single clickable URL, then streams backend logs until Ctrl-C.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${LUMINARY_PORT:-7820}"
DIST="$REPO_ROOT/frontend/dist/index.html"

_info() { echo -e "\033[0;36m$*\033[0m"; }

if [ ! -f "$DIST" ]; then
    echo "No frontend build found at $DIST" >&2
    echo "Build it first:  make build" >&2
    exit 1
fi

cd "$REPO_ROOT/backend"
DATA_DIR="$REPO_ROOT/.luminary" \
LUMINARY_MODE=prod \
LUMINARY_SURFACE_TIER=public \
    uv run uvicorn app.main:app --port "$PORT" 2>&1 &
SERVER_PID=$!

cleanup() {
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

_info "Starting Luminary on http://localhost:${PORT} ..."
i=0
until curl -sf --max-time 2 "http://localhost:${PORT}/health" > /dev/null 2>&1; do
    i=$((i + 1))
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "Backend exited before becoming ready." >&2
        exit 1
    fi
    [ "$i" -ge 60 ] && { _info "Backend not ready after 60s — continuing"; break; }
    sleep 1
done

echo -e "\033[1;32m  Luminary is ready\033[0m  --  http://localhost:${PORT}"

wait "$SERVER_PID"
