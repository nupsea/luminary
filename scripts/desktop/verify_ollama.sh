#!/usr/bin/env bash
# Prove the staged Ollama infers on Windows or Linux, not just that it starts.
#
# `ollama serve` starts happily without a working runner; a missing library only
# surfaces at the first generation. A CI runner has no GPU, so this proves the
# layout and the CPU path. Which accelerator a real machine gets is printed from
# Ollama's own discovery line, never assumed.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

case "$DESKTOP_OS" in
    linux) EXE="ollama" ;;
    windows) EXE="ollama.exe" ;;
    macos) _die "macOS verifies Ollama with scripts/macos/verify_ollama.sh" ;;
    *) _die "no desktop bundle for $(uname -s)" ;;
esac

OL_STAGE="${1:-$STAGE/ollama}"
LIB="$OL_STAGE/lib/ollama"
PROBE_MODEL="${PROBE_MODEL:-qwen2.5:0.5b}"
PORT="${PORT:-11435}"
MODELS_DIR="${OLLAMA_PROBE_MODELS:-$BUILD_DIR/probe-models}"
LOG="$BUILD_DIR/ollama-probe.log"
FAILED=0
_fail() { printf '\033[1;31m  FAIL: %s\033[0m\n' "$*" >&2; FAILED=1; }
_pass() { printf '\033[1;32m  ok\033[0m   %s\n' "$*"; }

_step "Structure"
[ -x "$OL_STAGE/$EXE" ] && _pass "$EXE present" || _fail "no $EXE"
for runner in cuda_v13 vulkan; do
    [ -d "$LIB/$runner" ] && _pass "$runner runner present" || _fail "no $runner runner"
done
[ ! -e "$LIB/cuda_v12" ] && _pass "CUDA 12 left out" || _fail "CUDA 12 shipped"

_step "Serving on 127.0.0.1:$PORT"
mkdir -p "$MODELS_DIR"
# The environment the shell gives it (supervisor.rs base_env), not ours.
if [ "$DESKTOP_OS" = windows ]; then
    child_env=(SystemRoot="$SYSTEMROOT" USERPROFILE="$USERPROFILE" TEMP="$TEMP" TMP="$TMP"
               PATH="/c/Windows/System32:/c/Windows")
else
    child_env=(HOME="$HOME" PATH=/usr/bin:/bin)
fi
env -i "${child_env[@]}" \
    OLLAMA_HOST="127.0.0.1:$PORT" \
    OLLAMA_MODELS="$(native_path "$MODELS_DIR")" \
    OLLAMA_LIBRARY_PATH="$(native_path "$LIB")" \
    "$OL_STAGE/$EXE" serve >"$LOG" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT

up=0
for _ in $(seq 1 60); do
    curl -sf "http://127.0.0.1:$PORT/api/version" >/dev/null 2>&1 && { up=1; break; }
    kill -0 $SRV 2>/dev/null || break
    sleep 1
done
if [ "$up" = 1 ]; then
    _pass "serve up ($(curl -s "http://127.0.0.1:$PORT/api/version"))"
else
    _fail "serve never came up"; tail -20 "$LOG" >&2
    exit 1
fi

_step "Pulling $PROBE_MODEL"
if curl -sf "http://127.0.0.1:$PORT/api/pull" -d "{\"model\":\"$PROBE_MODEL\",\"stream\":false}" \
        | grep -q '"status":"success"'; then
    _pass "pull succeeded over HTTP"
else
    _fail "pull failed"
fi

_step "Generating (forces a runner to load)"
resp="$(curl -sf --max-time 300 "http://127.0.0.1:$PORT/api/generate" \
    -d "{\"model\":\"$PROBE_MODEL\",\"prompt\":\"Reply with the single word: ready\",\"stream\":false}" 2>&1)"
text="$(echo "$resp" | sed -n 's/.*"response":"\([^"]*\)".*/\1/p')"
if [ -n "$text" ]; then
    _pass "generated: $(echo "$text" | head -c 60)"
else
    _fail "generation produced no text"; echo "$resp" | head -c 400 >&2
    tail -30 "$LOG" >&2
fi

_step "What Ollama discovered"
grep -iE 'inference compute|discover|no compatible GPUs|library=' "$LOG" | tail -5 | sed 's/^/    /' \
    || _info "no discovery line in $LOG"

kill $SRV 2>/dev/null; wait $SRV 2>/dev/null
echo
[ "$FAILED" = 0 ] && printf '\033[1;32mollama verified\033[0m\n' || printf '\033[1;31mollama verification FAILED\033[0m\n'
exit "$FAILED"
