#!/usr/bin/env bash
# Verify a Windows or Linux stage is relocatable and actually boots, before an
# installer is built from it.
#
#   scripts/desktop/verify_stage.sh [path-to-stage]
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

case "$DESKTOP_OS" in
    linux | windows) ;;
    macos) _die "macOS verifies its stage with scripts/macos/verify_stage.sh" ;;
    *) _die "no desktop bundle for $(uname -s)" ;;
esac

STAGE="${1:-$STAGE}"
PY="$(staged_python)"
FAILED=0
_fail() { printf '\033[1;31m  FAIL: %s\033[0m\n' "$*" >&2; FAILED=1; }
_pass() { printf '\033[1;32m  ok\033[0m   %s\n' "$*"; }

[ -x "$PY" ] || _die "no staged interpreter at $PY"
mkdir -p "$BUILD_DIR"

_step "1. No build-machine paths"
# Only full build-machine roots, in both spellings a Windows build writes them
# in. Bare fragments match prose in package METADATA.
patterns=()
for root in "$BUILD_DIR" "$UV_PYTHON_INSTALL_DIR" "$(uv cache dir 2>/dev/null)"; do
    [ -n "$root" ] || continue
    patterns+=(-e "$root" -e "$(native_path "$root")")
done
hits="$(grep -rlF "${patterns[@]}" "$STAGE" --binary-files=without-match 2>/dev/null || true)"
if [ -n "$hits" ]; then
    _fail "build-machine paths found:"; echo "$hits" | head -10 >&2
else
    _pass "no build-machine paths"
fi
[ -e "$STAGE/python/pyvenv.cfg" ] && _fail "pyvenv.cfg leaked into the stage" || _pass "no pyvenv.cfg"

_step "2. Interpreter sees itself inside the stage"
if "$PY" -I -c '
import os, sys
stage = os.path.normcase(os.path.realpath(sys.argv[1]))
prefix = os.path.normcase(os.path.realpath(sys.prefix))
print(sys.prefix)
sys.exit(0 if prefix.startswith(stage) else 1)
' "$(native_path "$STAGE")"; then
    _pass "sys.prefix is inside the stage"
else
    _fail "sys.prefix escaped the stage, or the interpreter would not start"
fi

_step "3. Native imports"
"$PY" -I "$(native_path "$REPO_ROOT/scripts/desktop/verify_imports.py")" \
    && _pass "dependency set is exactly as shipped" || _fail "dependency set is wrong"

_step "4. Backend imports through the .pth"
# Proves the .pth resolved without PYTHONPATH, surface-manifest.json is where
# parents[2] expects it, and import-time router registration succeeded.
ERRF="$BUILD_DIR/verify-import.err"
if out="$(DATA_DIR="$(mktemp -d)" LUMINARY_MODE=public "$PY" -I -c \
        'import app.main as m; print(m._APP_VERSION)' 2>"$ERRF")"; then
    _pass "import app.main -> version $out"
else
    _fail "import app.main failed:"; tail -20 "$ERRF" >&2
fi

_step "5. Server boots and serves the SPA"
MARKER="$BUILD_DIR/verify-stage.marker"
touch "$MARKER"
D="$(mktemp -d)"; PORT=7931
DATA_DIR="$D" LUMINARY_MODE=public LOG_LEVEL=WARNING \
    "$PY" -I -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --no-access-log \
    >"$BUILD_DIR/verify-server.log" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
ready=0
for _ in $(seq 1 120); do
    curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && { ready=1; break; }
    kill -0 $SRV 2>/dev/null || break
    sleep 1
done
if [ "$ready" = 1 ]; then
    _pass "/health responded"
    curl -sf "http://127.0.0.1:$PORT/" | grep -q 'id="root"' \
        && _pass "SPA served from stage" || _fail "SPA not served"
    curl -sf "http://127.0.0.1:$PORT/api/documents?page=1&page_size=1" >/dev/null \
        && _pass "/api reachable" || _fail "/api not reachable"
    [ -f "$D/luminary.db" ] && _pass "alembic created luminary.db" || _fail "no luminary.db"
else
    _fail "server never became healthy"; tail -30 "$BUILD_DIR/verify-server.log" >&2
fi
kill $SRV 2>/dev/null; wait $SRV 2>/dev/null
rm -rf "$D"

_step "6. yt-dlp runs the way the backend spawns it"
if out="$("$PY" -I -m yt_dlp --version 2>&1 | tail -1)"; then
    _pass "python -m yt_dlp ($out)"
else
    _fail "python -m yt_dlp failed: $out"
fi
if [ "$DESKTOP_OS" = windows ]; then
    launchers="$(find "$STAGE/python/Scripts" -mindepth 1 2>/dev/null || true)"
    [ -z "$launchers" ] && _pass "no dead console-script launchers" \
        || { _fail "launchers with an embedded build path remain:"; echo "$launchers" >&2; }
else
    RELOC="$(mktemp -d)/reloc"
    cp -a "$STAGE/python" "$RELOC"
    if out="$("$RELOC/bin/yt-dlp" --version 2>&1 | tail -1)"; then
        _pass "bin/yt-dlp runs from a relocated copy ($out)"
    else
        _fail "bin/yt-dlp failed after relocation: $out"
    fi
    rm -rf "$(dirname "$RELOC")"
fi

_step "7. Nothing was written inside the stage"
# An install directory is not writable by the app on either platform, so a
# write here is a crash on a user's machine.
newer="$(find "$STAGE" -type f -newer "$MARKER" 2>/dev/null | head -5)"
[ -z "$newer" ] && _pass "stage untouched by the boot test" \
    || { _fail "files written inside the stage during boot:"; echo "$newer" >&2; }
rm -f "$MARKER"

_step "8. Stage size"
size_mb="$(du -sm "$STAGE" | cut -f1)"
if [ -z "$STAGE_SIZE_BUDGET_MB" ]; then
    _pass "${size_mb}MB (no budget on $DESKTOP_OS -- reported so growth is visible)"
elif [ "$size_mb" -le "$STAGE_SIZE_BUDGET_MB" ]; then
    _pass "${size_mb}MB, within the ${STAGE_SIZE_BUDGET_MB}MB budget"
else
    _fail "stage is ${size_mb}MB, over the ${STAGE_SIZE_BUDGET_MB}MB budget by $((size_mb - STAGE_SIZE_BUDGET_MB))MB"
    echo "  the largest directories:" >&2
    # staged_site, not a literal path: Windows stages python/Lib/site-packages
    # where unix stages python/lib/python3.13/site-packages.
    du -sm "$STAGE"/* "$(staged_site)"/* 2>/dev/null | sort -rn | head -12 >&2
fi

_step "9. Path lengths"
# Relative to the stage root, because that is what gets appended to the install
# directory on the user's machine.
long="$(cd "$STAGE" && find . -mindepth 1 | sed 's|^\./||' \
    | awk -v n="$STAGE_PATH_BUDGET" 'length($0) > n { print length($0), $0 }' | sort -rn)"
if [ -z "$long" ]; then
    longest="$(cd "$STAGE" && find . -mindepth 1 | sed 's|^\./||' | awk '{ print length($0) }' \
        | sort -rn | head -1)"
    _pass "longest path ${longest} chars, within the ${STAGE_PATH_BUDGET} budget"
else
    _fail "$(echo "$long" | wc -l | tr -d ' ') path(s) over ${STAGE_PATH_BUDGET} chars:"
    echo "$long" | head -10 >&2
fi

echo
[ "$FAILED" = 0 ] && printf '\033[1;32mstage verified\033[0m\n' || printf '\033[1;31mstage verification FAILED\033[0m\n'
exit "$FAILED"
