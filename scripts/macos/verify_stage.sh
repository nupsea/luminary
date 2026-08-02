#!/usr/bin/env bash
# Verify a staged tree (or the Resources dir of a built .app) is relocatable and
# actually boots. Runs before any Tauri or signing work exists, so the highest-
# uncertainty part of the pipeline fails here rather than after notarization.
#
#   scripts/macos/verify_stage.sh [path-to-stage]
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

STAGE="${1:-$STAGE}"
PY="$(staged_python)"
FAILED=0
_fail() { printf '\033[1;31m  FAIL: %s\033[0m\n' "$*" >&2; FAILED=1; }
_pass() { printf '\033[1;32m  ok\033[0m   %s\n' "$*"; }

[ -x "$PY" ] || _die "no staged interpreter at $PY"

_step "1. No build-machine absolute paths"
# Only paths that will not exist on a user's Mac. Scanning for /opt/homebrew or
# /usr/local as text is pure noise -- they appear in vendored docs, package
# METADATA and sysconfig data, none of which is consulted at runtime. What
# genuinely breaks is a *load command* pointing outside the bundle, which step
# 1b checks properly.
# Bare fragments like "\.venv/bin" are too weak -- they match prose in package
# METADATA ("source .venv/bin/activate"). Only full build-machine roots.
PAT="$HOME/\.cache/uv|$BUILD_DIR|$UV_PYTHON_INSTALL_DIR"
hits="$(grep -rlE "$PAT" "$STAGE" --binary-files=without-match 2>/dev/null || true)"
if [ -n "$hits" ]; then
    _fail "build-machine paths found:"; echo "$hits" | head -10 >&2
else
    _pass "no build-machine paths"
fi
if [ -e "$STAGE/python/pyvenv.cfg" ]; then _fail "pyvenv.cfg leaked into the stage"; else _pass "no pyvenv.cfg"; fi

_step "1b. No Mach-O links outside the bundle"
# A library's own LC_ID_DYLIB (its install name) routinely records the path it
# was BUILT at -- PBS's prefix, a wheel builder's /Users/runner tree, homebrew's
# libomp. That is identity, not linkage: consumers here resolve through @rpath,
# so the IDs are inert. Only LC_LOAD_DYLIB entries can actually break dyld, so
# the install name is excluded before judging.
n=0; bad=0
while IFS= read -r -d '' f; do
    n=$((n + 1))
    id="$(otool -D "$f" 2>/dev/null | tail -n +2)"
    deps="$(otool -L "$f" 2>/dev/null | tail -n +2 | grep -vF "${id:-$$NOMATCH}")"
    if echo "$deps" | grep -qE '^[[:space:]]+/(opt|Users|usr/local|home)/'; then
        _fail "external dylib dep: $f"
        echo "$deps" | grep -E '^[[:space:]]+/(opt|Users|usr/local|home)/' >&2
        bad=1
    fi
done < <(macho_files "$STAGE")
[ "$bad" = 0 ] && _pass "$n Mach-O files, no external linkage"

_step "2. Interpreter sees itself inside the stage"
if out="$("$PY" -I -c 'import sys; print(sys.prefix)' 2>&1)"; then
    case "$out" in
        "$STAGE"/*) _pass "sys.prefix = $out" ;;
        *) _fail "sys.prefix escaped the stage: $out" ;;
    esac
else
    _fail "interpreter would not start: $out"
fi

_step "3. No absolute or dangling symlinks"
bad=0
while IFS= read -r l; do
    t="$(readlink "$l")"
    case "$t" in /*) _fail "absolute symlink: $l -> $t"; bad=1 ;; esac
    [ -e "$l" ] || { _fail "dangling symlink: $l -> $t"; bad=1; }
done < <(find "$STAGE" -type l)
[ "$bad" = 0 ] && _pass "symlinks are relative and resolve"

_step "4. Native imports (unsigned surface)"
"$PY" -I - <<'PYEOF'
import importlib, importlib.util, sys

# Everything the shipped bundle must be able to import.
required = ["numpy", "scipy", "sklearn", "torch", "onnxruntime", "transformers",
            "sentence_transformers", "gliner", "lancedb", "pyarrow",
            "kuzu", "fitz", "PIL", "litellm", "langgraph", "keyring",
            "fastapi", "uvicorn", "alembic", "sqlalchemy", "aiosqlite",
            "yt_dlp", "trafilatura", "tree_sitter", "cloudscraper", "pip"]

# Packages that must NOT be here. `av` and its dependants carry libx264/libx265
# (GPL-2.0-or-later) inside their wheels, and Luminary ships Apache-2.0 -- they
# are installed after the fact as the `transcription` component, never bundled.
# `optimum`/`onnx` are simply unused; they cost ~49MB when they crept in.
forbidden = ["av", "faster_whisper", "ctranslate2", "optimum", "onnx"]

bad = []
for m in required:
    try:
        importlib.import_module(m)
    except Exception as e:
        bad.append(f"missing {m}: {type(e).__name__}: {e}")
for m in forbidden:
    if importlib.util.find_spec(m) is not None:
        bad.append(f"{m} must not ship in the bundle")

print(f"    {len(required) - len([b for b in bad if b.startswith('missing')])}"
      f"/{len(required)} required present, {len(forbidden)} excluded")
if bad:
    print("\n".join("    " + b for b in bad), file=sys.stderr)
    sys.exit(1)
PYEOF
[ $? -eq 0 ] && _pass "dependency set is exactly as shipped" || _fail "dependency set is wrong"

_step "5. Backend imports through the .pth"
# This single import transitively proves: _luminary.pth resolved, the backend
# package is on sys.path without PYTHONPATH, surface-manifest.json is where
# parents[2] expects it (a missing manifest is boot-fatal at import time), and
# import-time router registration succeeded.
ERRF="$BUILD_DIR/verify-import.err"
if out="$(DATA_DIR="$(mktemp -d)" LUMINARY_MODE=public "$PY" -I -c \
        'import app.main as m; print(m._APP_VERSION)' 2>"$ERRF")"; then
    _pass "import app.main -> version $out"
else
    _fail "import app.main failed:"; tail -20 "$ERRF" >&2
fi

_step "6. Server boots and serves the SPA"
D="$(mktemp -d)"; PORT=7931
DATA_DIR="$D" LUMINARY_MODE=public LOG_LEVEL=WARNING \
    "$PY" -I -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --no-access-log \
    >"$BUILD_DIR/verify-server.log" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
ready=0
for _ in $(seq 1 90); do
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

_step "7. Console scripts survive relocation"
# youtube_downloader.py resolves `yt-dlp` through PATH and spawns it, so the
# shebang trampoline has to work from a moved copy, not just in place.
if [ -f "$STAGE/python/bin/yt-dlp" ]; then
    RELOC="$(mktemp -d)/reloc"
    ditto "$STAGE/python" "$RELOC/python" 2>/dev/null
    if out="$("$RELOC/python/bin/yt-dlp" --version 2>&1 | tail -1)"; then
        _pass "yt-dlp runs from a relocated copy ($out)"
    else
        _fail "yt-dlp failed after relocation: $out"
    fi
    rm -rf "$(dirname "$RELOC")"
else
    _fail "bin/yt-dlp missing (youtube ingestion spawns it by name)"
fi

_step "8. Nothing was written inside the stage"
# In the .app this is enforced by the code signature; here we approximate it by
# looking for anything newer than the staging run.
if newer="$(find "$STAGE" -type f -newer "$STAGE/surface-manifest.json" ! -path '*/verify-*' 2>/dev/null | head -5)"; then
    [ -z "$newer" ] && _pass "stage untouched by the boot test" \
        || { _fail "files written inside the stage during boot:"; echo "$newer" >&2; }
fi

echo
[ "$FAILED" = 0 ] && printf '\033[1;32mstage verified\033[0m\n' || printf '\033[1;31mstage verification FAILED\033[0m\n'
exit "$FAILED"
