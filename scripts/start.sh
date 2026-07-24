#!/usr/bin/env bash
# start.sh — launch the production build: SPA + API on one port (7820), no reload.
# The frontend must be built first (`make build`). Polls /health, prints a ready
# banner with the single clickable URL, then streams backend logs until Ctrl-C.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${LUMINARY_PORT:-7820}"
DIST="$REPO_ROOT/frontend/dist/index.html"

_info() { echo -e "\033[0;36m$*\033[0m"; }
_warn() { echo -e "\033[0;33m$*\033[0m" >&2; }

if [ ! -f "$DIST" ]; then
    echo "No frontend build found at $DIST" >&2
    echo "Build it first:  make build" >&2
    exit 1
fi

cd "$REPO_ROOT/backend"
DATA_DIR="$REPO_ROOT/.luminary" \
LUMINARY_MODE=public \
    uv run uvicorn app.main:app --port "$PORT" 2>&1 &
SERVER_PID=$!

cleanup() {
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

_info "Starting Luminary on http://localhost:${PORT} ..."
_info "First run downloads ML models and is slower; the log below is expected."
ready=0
i=0
while [ "$i" -lt 90 ]; do
    if curl -sf --max-time 2 "http://localhost:${PORT}/health" > /dev/null 2>&1; then
        ready=1
        break
    fi
    i=$((i + 1))
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "Backend exited before becoming ready. Scroll up for the error." >&2
        exit 1
    fi
    sleep 1
done

if [ "$ready" -eq 1 ]; then
    echo -e "\033[1;32m  Luminary is ready\033[0m  --  open http://localhost:${PORT}"
    echo -e "\033[0;90m  (ML models keep warming in the background for a few more seconds — that's normal.)\033[0m"
else
    _warn "  Still starting after ${i}s — the server hasn't answered /health yet."
    _warn "  This is usually a slow first-run model download; watch the log above, then open http://localhost:${PORT}"
fi

# Non-fatal LLM pre-flight: the moat loop (card generation, chat, teach-back) needs
# a local model. Warn — never block — so the app's own first-run guide stays the
# primary path. Uses the Ollama HTTP API so it doesn't depend on the CLI being on PATH.
CHAT_MODEL="${LUMINARY_CHAT_MODEL:-llama3.2}"
if ! curl -sf --max-time 2 http://localhost:11434/api/version >/dev/null 2>&1; then
    _warn "  Ollama isn't running — card generation, chat, and teach-back are unavailable."
    _warn "  Start it with:  ollama serve   (or re-run:  make install)"
elif ! curl -sf --max-time 2 http://localhost:11434/api/tags 2>/dev/null | grep -q "\"${CHAT_MODEL}"; then
    _warn "  Ollama is up but the default model isn't pulled."
    _warn "  Pull it with:  ollama pull ${CHAT_MODEL}"
fi

wait "$SERVER_PID"
