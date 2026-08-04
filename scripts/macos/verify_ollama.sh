#!/usr/bin/env bash
# Prove the staged Ollama actually infers, not just that it answers /api/version.
#
# `ollama serve` starts happily without a working runner; the failure only
# surfaces at the first generation, when it spawns llama-server and compiles
# Metal shaders. A health check alone would let a broken bundle ship, which is
# exactly how a dangling-symlink or wrong-arch runner reaches users.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

OL_STAGE="${1:-$STAGE/ollama}"
PROBE_MODEL="${PROBE_MODEL:-qwen2.5:0.5b}"
PORT="${PORT:-11435}"
MODELS_DIR="${OLLAMA_PROBE_MODELS:-$BUILD_DIR/probe-models}"
FAILED=0
_fail() { printf '\033[1;31m  FAIL: %s\033[0m\n' "$*" >&2; FAILED=1; }
_pass() { printf '\033[1;32m  ok\033[0m   %s\n' "$*"; }

_step "Structure"
[ -x "$OL_STAGE/ollama" ] && _pass "ollama present" || _fail "no ollama binary"
[ -x "$OL_STAGE/llama-server" ] && _pass "llama-server present" || _fail "no llama-server"

for b in ollama llama-server; do
    archs="$(lipo -archs "$OL_STAGE/$b" 2>/dev/null)"
    [ "$archs" = "arm64" ] && _pass "$b is arm64-only" || _fail "$b archs = $archs"
done

_step "No linkage or symlink escaping the bundle"
bad=0
while IFS= read -r l; do
    t="$(readlink "$l")"
    case "$t" in /*) _fail "absolute symlink $l -> $t"; bad=1 ;; esac
    [ -e "$l" ] || { _fail "dangling symlink $l -> $t"; bad=1; }
done < <(find "$OL_STAGE" -type l)
while IFS= read -r -d '' f; do
    if otool -L "$f" 2>/dev/null | tail -n +2 | grep -qE '^\s+/(opt|Users|usr/local)/'; then
        _fail "external dylib dep in $f"; bad=1
    fi
done < <(macho_files "$OL_STAGE")
[ "$bad" = 0 ] && _pass "self-contained"

_step "Serving on 127.0.0.1:$PORT"
mkdir -p "$MODELS_DIR"
env -i HOME="$HOME" PATH=/usr/bin:/bin \
    OLLAMA_HOST="127.0.0.1:$PORT" \
    OLLAMA_MODELS="$MODELS_DIR" \
    OLLAMA_LIBRARY_PATH="$OL_STAGE" \
    "$OL_STAGE/ollama" serve >"$BUILD_DIR/ollama-probe.log" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT

up=0
for _ in $(seq 1 30); do
    curl -sf "http://127.0.0.1:$PORT/api/version" >/dev/null 2>&1 && { up=1; break; }
    kill -0 $SRV 2>/dev/null || break
    sleep 1
done
if [ "$up" = 1 ]; then
    _pass "serve up ($(curl -s "http://127.0.0.1:$PORT/api/version"))"
else
    _fail "serve never came up"; tail -20 "$BUILD_DIR/ollama-probe.log" >&2
    exit 1
fi

_step "Pulling $PROBE_MODEL"
if curl -sf "http://127.0.0.1:$PORT/api/pull" -d "{\"model\":\"$PROBE_MODEL\",\"stream\":false}" \
        | grep -q '"status":"success"'; then
    _pass "pull succeeded over HTTP (no subprocess, no PATH dependency)"
else
    _fail "pull failed"
fi

_step "Generating (forces llama-server spawn + Metal shader compile)"
resp="$(curl -sf --max-time 180 "http://127.0.0.1:$PORT/api/generate" \
    -d "{\"model\":\"$PROBE_MODEL\",\"prompt\":\"Reply with the single word: ready\",\"stream\":false}" 2>&1)"
if echo "$resp" | grep -q '"response"' && [ -n "$(echo "$resp" | sed -n 's/.*"response":"\([^"]*\)".*/\1/p')" ]; then
    _pass "generated: $(echo "$resp" | sed -n 's/.*"response":"\([^"]*\)".*/\1/p' | head -c 60)"
else
    _fail "generation produced no text"; echo "$resp" | head -c 400 >&2
    tail -30 "$BUILD_DIR/ollama-probe.log" >&2
fi

kill $SRV 2>/dev/null; wait $SRV 2>/dev/null
echo
[ "$FAILED" = 0 ] && printf '\033[1;32mollama verified\033[0m\n' || printf '\033[1;31mollama verification FAILED\033[0m\n'
exit "$FAILED"
