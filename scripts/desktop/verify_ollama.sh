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
[ -d "$LIB/vulkan" ] && _pass "vulkan runner present" || _fail "no vulkan runner"
# CUDA is a download, not a payload: it is 1.8GB of the archive and 629MB of it
# is what put the Windows stage past what NSIS can pack. A staged CUDA runner
# means the exclusion in stage_ollama.sh stopped matching.
if compgen -G "$LIB/cuda_v*" >/dev/null; then
    _fail "CUDA shipped in the installer: $(cd "$LIB" && echo cuda_v*)"
else
    _pass "CUDA left out (offered as a download instead)"
fi
[ -s "$OL_STAGE/ENGINE_VERSION" ] && _pass "stamped $(tr -d '\r\n' < "$OL_STAGE/ENGINE_VERSION")" \
    || _fail "no ENGINE_VERSION; the shell cannot tell whether its copy is current"

# Everything below runs from a COPY, because that is what the app runs: the
# shell copies the engine into the writable library directory and spawns it from
# there. Ollama finds its runners relative to its own executable, so a tree that
# infers in place is not evidence that the relocated one does.
_step "Relocating the engine the way the shell does"
RELOC="$BUILD_DIR/engine-copy"
rm -rf "$RELOC"
mkdir -p "$RELOC"
cp -a "$OL_STAGE" "$RELOC/ollama"
OL_RUN="$RELOC/ollama"
LIB_RUN="$OL_RUN/lib/ollama"
_pass "copied to $OL_RUN"

# The relink in stage_ollama.sh records the directory an inherited RPATH already
# implied, and `vulkan/libggml-vulkan.so` -- the file it exists for -- is never
# loaded on a CPU-only runner, so the generation below cannot exercise it. This
# does, statically: a library the stage SHIPS must resolve from inside the tree.
# One the host owns is skipped rather than failed, because a CI runner has no
# Vulkan loader and `libvulkan.so.1` is legitimately absent here.
#
# `edges` is reported because a predicate that matches nothing is not a passing
# check, it is a dead one: if the engine ever stops shipping a library that
# another shipped library needs, this must say so rather than go quietly green.
if [ "$DESKTOP_OS" = linux ]; then
    _step "Resolving the engine's own libraries"
    unresolved="" edges=0 seen=0
    while IFS= read -r lib; do
        seen=$((seen + 1))
        while IFS= read -r need; do
            [ -n "$need" ] || continue
            find "$LIB_RUN" -name "$need" -print -quit 2>/dev/null | grep -q . || continue
            edges=$((edges + 1))
            if ldd "$lib" 2>/dev/null | awk -v n="$need" '$1 == n && /not found/ {found=1} END {exit !found}'; then
                unresolved="$unresolved ${lib#"$OL_RUN"/} -> $need;"
            fi
        done < <(patchelf --print-needed "$lib" 2>/dev/null)
    done < <(find "$LIB_RUN" -type f \( -name '*.so' -o -name '*.so.*' \))
    if [ -n "$unresolved" ]; then
        _fail "shipped libraries that do not resolve:$unresolved"
    elif [ "$edges" = 0 ]; then
        _fail "no shipped library depends on another ($seen examined); this check cannot fail, so it is not checking"
    else
        _pass "$seen libraries, $edges shipped dependencies, all resolve"
    fi
fi

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
    OLLAMA_LIBRARY_PATH="$(native_path "$LIB_RUN")" \
    "$OL_RUN/$EXE" serve >"$LOG" 2>&1 &
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
rm -rf "$RELOC"
echo
[ "$FAILED" = 0 ] && printf '\033[1;32mollama verified\033[0m\n' || printf '\033[1;31mollama verification FAILED\033[0m\n'
exit "$FAILED"
