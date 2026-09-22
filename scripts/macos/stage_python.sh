#!/usr/bin/env bash
# Stage a fully relocatable Python runtime with every backend dependency installed.
#
# Deliberately NOT a venv. A venv always writes an absolute `home = ...` into
# pyvenv.cfg pointing at the base interpreter, and `uv venv --relocatable` only
# rewrites console-script shebangs -- it does not fix that. Instead we install
# straight into the python-build-standalone distribution's own site-packages.
# CPython derives sys.prefix by walking up from the resolved executable to the
# lib/pythonX.Y/os.py landmark, and the PBS binary links
# @executable_path/../lib/libpython3.13.dylib, so the result contains no
# absolute paths at all and relocates into the .app unchanged.
#
# The dependency profile, prunes and .pth are shared with Windows and Linux
# (scripts/desktop/lib.sh). What is here is what only a signed Mac bundle needs.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PY_STAGE="$STAGE/python"

mkdir -p "$BUILD_DIR"
command -v uv >/dev/null || _die "uv not found"

_step "Fetching interpreter $PBS_VERSION"
uv python install "$PBS_VERSION"
SRC="$UV_PYTHON_INSTALL_DIR/$PBS_VERSION"
[ -x "$SRC/bin/python$PY_MINOR" ] || _die "interpreter not at $SRC/bin/python$PY_MINOR"

_step "Copying interpreter into the stage"
rm -rf "$PY_STAGE"
mkdir -p "$STAGE"
# ditto, not cp -R: it preserves the bin/python -> python3.13 symlinks and
# extended attributes that Tauri's own resource copier mangles.
ditto "$SRC" "$PY_STAGE"
PY="$(staged_python)"
STDLIB="$(staged_stdlib)"
SITE="$(staged_site)"

# uv marks the interpreters it manages EXTERNALLY-MANAGED so nobody pip-installs
# into the shared toolchain. This staged copy is a private runtime we own and
# ship, and installing into it is the entire point, so the marker is wrong here.
rm -f "$STDLIB/EXTERNALLY-MANAGED"

install_shipping_dependencies "$PY"
prune_test_suites "$SITE"
write_backend_pth "$SITE"

_step "Sanitizing build-machine paths"
# _sysconfigdata__*.py records the interpreter's build-time prefix, which is the
# build machine's uv python directory. Nothing in a shipped bundle compiles
# extensions, so those config vars are inert -- but the path leaks a local
# layout into a distributed artifact and points somewhere that does not exist on
# a user's Mac. Replace it with an obviously synthetic one.
sanitized=0
while IFS= read -r f; do
    LC_ALL=C sed -i '' "s|$SRC|/opt/luminary/python|g" "$f" && sanitized=$((sanitized + 1))
done < <(grep -rlF "$SRC" "$PY_STAGE" --binary-files=without-match 2>/dev/null || true)
_info "sanitized $sanitized files"

relocatable_shebangs "$PY" "$PY_STAGE/bin"

_step "Pruning the interpreter"
# tkinter/tcl/tk is ~15MB and nothing in the backend imports it.
rm -rf "$PY_STAGE"/lib/tcl8* "$PY_STAGE"/lib/tk8* "$PY_STAGE"/lib/itcl* \
       "$PY_STAGE"/lib/thread* "$PY_STAGE"/lib/sqlite3* \
       "$STDLIB"/{tkinter,idlelib,turtledemo,ensurepip} \
       "$STDLIB/test" \
       "$STDLIB/lib-dynload"/_tkinter*.so \
       "$PY_STAGE/include" "$PY_STAGE/share" 2>/dev/null || true

prune_dependencies "$SITE"
byte_compile "$PY" "$STDLIB"
if [ -d "$STAGE/backend" ]; then byte_compile "$PY" "$STAGE/backend"; fi

_step "Thinning universal extensions to arm64"
# Several wheels (lxml, scipy, ml_dtypes, ...) ship universal2 binaries. We
# build an Apple-Silicon-only app, so the Intel slices are pure weight.
thinned=0
while IFS= read -r -d '' f; do
    archs="$(lipo -archs "$f" 2>/dev/null || true)"
    if echo "$archs" | grep -q arm64 && echo "$archs" | grep -q x86_64; then
        lipo -thin arm64 "$f" -output "$f.thin" 2>/dev/null \
            && mv -f "$f.thin" "$f" && thinned=$((thinned + 1))
    fi
done < <(macho_files "$SITE")
_info "thinned $thinned universal binaries"

_step "Breaking hardlinks back into the uv cache"
# uv installs by hardlinking from ~/.cache/uv. If those links survive, a later
# `codesign --force` would mutate the shared cache inode rather than our copy.
while IFS= read -r -d '' f; do
    if [ "$(stat -f %l "$f")" -gt 1 ]; then
        cp -p "$f" "$f.unlink" && mv -f "$f.unlink" "$f"
    fi
done < <(macho_files "$SITE")

_info "runtime staged: $(du -sh "$PY_STAGE" | awk '{print $1}')"
