#!/usr/bin/env bash
# Stage a relocatable Python runtime for the Windows and Linux installers.
#
# Same method as scripts/macos/stage_python.sh, which explains why this is not a
# venv: dependencies go straight into python-build-standalone's own
# site-packages, and CPython finds its prefix relative to its own executable.
# macOS keeps a separate script for the steps only a signed bundle needs
# (thinning universal binaries, breaking hardlinks before codesign).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

case "$DESKTOP_OS" in
    linux | windows) ;;
    macos) _die "macOS stages its runtime with scripts/macos/stage_python.sh" ;;
    *) _die "no desktop bundle for $(uname -s)" ;;
esac
command -v uv >/dev/null || _die "uv not found"

PY_STAGE="$STAGE/python"
mkdir -p "$BUILD_DIR" "$STAGE"

_step "Fetching interpreter $PBS_VERSION"
uv python install "$PBS_VERSION"
SRC="$UV_PYTHON_INSTALL_DIR/$PBS_VERSION"
[ -d "$SRC" ] || _die "interpreter not at $SRC"

_step "Copying interpreter into the stage"
rm -rf "$PY_STAGE"
# cp -a keeps Linux's bin/python3 -> python3.13 as a relative symlink.
cp -a "$SRC" "$PY_STAGE"
PY="$(staged_python)"
STDLIB="$(staged_stdlib)"
SITE="$(staged_site)"
[ -x "$PY" ] || _die "interpreter not at $PY"

# uv marks the interpreters it manages EXTERNALLY-MANAGED so nobody pip-installs
# into the shared toolchain. This copy is a private runtime we own and ship.
rm -f "$STDLIB/EXTERNALLY-MANAGED"

install_shipping_dependencies "$PY"
prune_test_suites "$SITE"
write_backend_pth "$SITE"

_step "Sanitizing build-machine paths"
# Linux's _sysconfigdata records the interpreter's build-time prefix, as on
# macOS; a Windows build can write the same root with backslashes, forward
# slashes, or escaped inside a Python string. Inert at runtime, but it leaks a
# build layout into a distributed artifact. Text files only.
"$PY" - "$PY_STAGE" "$SRC" "$(native_path "$SRC")" <<'PYEOF'
import os, sys
root, *spellings = sys.argv[1:]
needles = set()
for s in spellings:
    needles.update({s, s.replace("\\", "/"), s.replace("\\", "\\\\")})
needles = sorted((n.encode() for n in needles if n), key=len, reverse=True)
count = 0
for d, _, files in os.walk(root):
    for name in files:
        p = os.path.join(d, name)
        if os.path.islink(p):
            continue
        try:
            with open(p, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        new = data
        for n in needles:
            new = new.replace(n, b"/opt/luminary/python")
        if new != data:
            with open(p, "wb") as fh:
                fh.write(new)
            count += 1
print(f"    sanitized {count} files")
PYEOF

if [ "$DESKTOP_OS" = windows ]; then
    _step "Removing console-script launchers"
    # uv's Windows launchers are .exe files with the build machine's interpreter
    # path embedded, so each one is dead once installed anywhere else, and none
    # can be rewritten the way a unix shebang can. Nothing needs them: the backend
    # runs yt-dlp as `python -m yt_dlp` and pip as `python -m pip`. A dead launcher
    # left on the backend's PATH is worse than none, because `shutil.which` finds it.
    rm -f "$PY_STAGE"/Scripts/*.exe
else
    relocatable_shebangs "$PY" "$PY_STAGE/bin"
fi

_step "Pruning the interpreter"
# tkinter/tcl/tk and the interpreter's own test suite: nothing in the backend imports them.
if [ "$DESKTOP_OS" = windows ]; then
    rm -rf "$PY_STAGE/tcl" "$PY_STAGE/include" "$PY_STAGE/libs" \
           "$STDLIB"/{tkinter,idlelib,turtledemo,ensurepip,test} \
           "$PY_STAGE"/DLLs/_tkinter.pyd "$PY_STAGE"/DLLs/tcl*.dll "$PY_STAGE"/DLLs/tk*.dll
else
    rm -rf "$PY_STAGE"/lib/tcl8* "$PY_STAGE"/lib/tk8* "$PY_STAGE"/lib/itcl* \
           "$PY_STAGE"/lib/thread* "$PY_STAGE"/lib/sqlite3* \
           "$STDLIB"/{tkinter,idlelib,turtledemo,ensurepip,test} \
           "$STDLIB"/lib-dynload/_tkinter*.so \
           "$PY_STAGE/include" "$PY_STAGE/share"
fi

prune_dependencies "$SITE"
byte_compile "$PY" "$STDLIB"
[ -d "$STAGE/backend" ] && byte_compile "$PY" "$STAGE/backend"

_info "runtime staged: $(du -sh "$PY_STAGE" | awk '{print $1}')"
