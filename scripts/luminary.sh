#!/usr/bin/env bash
# luminary.sh — start backend + frontend, stream backend logs, print ready URL.
#
# Usage: bash scripts/luminary.sh
#
# Behaviour:
#   1. Backend (uvicorn :8000) and frontend (Vite :5173) start in parallel.
#   2. All logs stream to stdout: [BACKEND] lines in cyan, [FRONTEND] in green.
#   3. The script polls /health, then the Vite port, then /documents.
#   4. Once the backend is up and at least one document is in the library
#      (or 30 s have elapsed with 0 docs), a ready banner + clickable URL is printed.
#   5. Backend logs continue until Ctrl-C, which cleanly stops both processes.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BACKEND_PORT=7820
FRONTEND_PORT=5173  # default; actual port detected from Vite output below

# ---------------------------------------------------------------------------
# Start processes — each piped through awk for prefixed, coloured output
# ---------------------------------------------------------------------------
(cd "$REPO_ROOT/backend" && uv run uvicorn app.main:app --reload --port "$BACKEND_PORT" 2>&1) \
    | awk 'BEGIN{p="\033[0;36m[BACKEND]\033[0m  "}{print p $0; fflush()}' &
BACKEND_PIPE_PID=$!

# Tee Vite output so we can scrape the actual bound port
VITE_LOG=$(mktemp)
(cd "$REPO_ROOT/frontend" && npm run dev 2>&1) \
    | tee "$VITE_LOG" \
    | awk 'BEGIN{p="\033[0;32m[FRONTEND]\033[0m "}{print p $0; fflush()}' &
FRONTEND_PIPE_PID=$!

# ---------------------------------------------------------------------------
# Cleanup on Ctrl-C / SIGTERM
# ---------------------------------------------------------------------------
_stop() {
    kill "$BACKEND_PIPE_PID" "$FRONTEND_PIPE_PID" 2>/dev/null || true
    wait "$BACKEND_PIPE_PID" "$FRONTEND_PIPE_PID" 2>/dev/null || true
    rm -f "$VITE_LOG"
    exit 0
}
trap _stop INT TERM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_info() { echo -e "\033[0;33m[LUMINARY]\033[0m $*"; }

# Poll a URL until it returns HTTP 200 or max_attempts seconds elapse.
_wait_http() {
    local url="$1" label="$2" max="${3:-60}"
    local i=0
    while ! curl -sf --max-time 2 "$url" > /dev/null 2>&1; do
        i=$((i + 1))
        [ "$i" -ge "$max" ] && { _info "$label not ready after ${max}s — continuing"; return 1; }
        sleep 1
    done
    return 0
}

# Return the total document count from the API (0 on any error).
_doc_count() {
    curl -sf --max-time 3 "http://localhost:${BACKEND_PORT}/documents?page=1&page_size=1" 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total',0))" 2>/dev/null \
        || echo 0
}

# ---------------------------------------------------------------------------
# Ready sequence
# ---------------------------------------------------------------------------

# Detect actual Vite port from its output (handles port conflicts where Vite
# increments to 5174, 5175, etc.)
_detect_vite_port() {
    local deadline=$((SECONDS + 30))
    while [ $SECONDS -lt $deadline ]; do
        local port
        port=$(grep -oE 'localhost:[0-9]+' "$VITE_LOG" 2>/dev/null | head -1 | cut -d: -f2)
        if [ -n "$port" ]; then
            echo "$port"
            return 0
        fi
        sleep 1
    done
    echo "$FRONTEND_PORT"  # fallback to default
}

_info "Waiting for frontend..."
FRONTEND_PORT=$(_detect_vite_port)
_wait_http "http://localhost:${FRONTEND_PORT}" "frontend" 60

# Wait for /documents to return HTTP 200 — this is the true readiness signal.
# /health returns 200 early during lifespan, but /documents only succeeds once
# the DB is initialised and all startup hooks have completed.
_info "Waiting for backend library API on :${BACKEND_PORT}..."
_wait_http "http://localhost:${BACKEND_PORT}/documents?page=1&page_size=1" "library API" 120

DOC_COUNT=$(_doc_count)

# ---------------------------------------------------------------------------
# Ready banner
# ---------------------------------------------------------------------------
echo
echo -e "\033[1;32m  Luminary is ready\033[0m  --  ${DOC_COUNT} document(s) in library"
echo -e "\033[1;32m  http://localhost:${FRONTEND_PORT}\033[0m"
echo

# Keep streaming until Ctrl-C
wait "$BACKEND_PIPE_PID" "$FRONTEND_PIPE_PID"
