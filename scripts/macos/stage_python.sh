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
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PY_STAGE="$STAGE/python"
REQ="$BUILD_DIR/requirements-app.txt"

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

# uv marks the interpreters it manages EXTERNALLY-MANAGED so nobody pip-installs
# into the shared toolchain. This staged copy is a private runtime we own and
# ship, and installing into it is the entire point, so the marker is wrong here.
rm -f "$PY_STAGE/lib/python$PY_MINOR/EXTERNALLY-MANAGED"

_step "Resolving the shipping dependency set"
# The shipping profile: no `dev` (Phoenix, pytest, ruff, tiktoken, reportlab --
# ~120MB that no user ever runs) but yes `full`, because the desktop app
# advertises YouTube/web/audio ingestion and must actually support it.
uv export --directory "$REPO_ROOT/backend" \
    --frozen --no-emit-project --no-default-groups --group full \
    --format requirements-txt --quiet -o "$REQ"
_info "$(grep -cE '^[a-zA-Z0-9]' "$REQ") packages"

_step "Installing dependencies into the staged interpreter"
# --system because this is not a venv: it is a private interpreter we own.
uv pip sync --python "$PY" --system "$REQ"

_step "Putting the backend source on sys.path"
SITE="$PY_STAGE/lib/python$PY_MINOR/site-packages"
[ -d "$SITE" ] || _die "site-packages not at $SITE"
# site.addpackage joins each line against the site dir, so a RELATIVE line
# relocates with the bundle. Four levels up from site-packages is the stage root
# (= Contents/Resources), where stage_payload.sh puts backend/.
# We launch with `python -I`, which drops PYTHONPATH, so this .pth is the only
# way the backend package is importable.
printf '../../../../backend\n' > "$SITE/_luminary.pth"

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

_step "Making console scripts relocatable"
# uv writes entry-point scripts with an absolute shebang pointing at the build
# machine's interpreter, which is dead on a user's Mac. We cannot just delete
# them: youtube_downloader.py resolves `yt-dlp` through PATH and spawns it as a
# subprocess, so bin/ has to work. Rewrite the shebang as the standard sh/Python
# polyglot trampoline -- sh runs the exec line, Python sees one string literal.
"$PY" - "$PY_STAGE/bin" <<'PYEOF'
import os, sys
bin_dir = sys.argv[1]
# sh reads '''' as two empty strings, so the word is `exec`, and `# ` starts a
# comment that swallows the trailing quotes. Python reads the whole line as one
# triple-quoted string. The quoting is exact -- a stray quote after `exec`
# breaks the sh side and the script falls through into its own Python body.
tramp = "#!/bin/sh\n''''exec \"$(dirname \"$0\")/python%d.%d\" \"$0\" \"$@\" # '''\n" % sys.version_info[:2]
fixed = 0
for name in os.listdir(bin_dir):
    p = os.path.join(bin_dir, name)
    if not os.path.isfile(p) or os.path.islink(p):
        continue
    try:
        with open(p, "rb") as fh:
            head = fh.readline()
            if not head.startswith(b"#!") or b"python" not in head:
                continue
            rest = fh.read()
    except OSError:
        continue
    with open(p, "wb") as fh:
        fh.write(tramp.encode())
        fh.write(rest)
    os.chmod(p, 0o755)
    fixed += 1
print(f"    rewrote {fixed} console-script shebangs")
PYEOF

_step "Pruning the interpreter"
# tkinter/tcl/tk is ~15MB and nothing in the backend imports it.
rm -rf "$PY_STAGE"/lib/tcl8* "$PY_STAGE"/lib/tk8* "$PY_STAGE"/lib/itcl* \
       "$PY_STAGE"/lib/thread* "$PY_STAGE"/lib/sqlite3* \
       "$PY_STAGE/lib/python$PY_MINOR"/{tkinter,idlelib,turtledemo,ensurepip} \
       "$PY_STAGE/lib/python$PY_MINOR/test" \
       "$PY_STAGE/lib/python$PY_MINOR/lib-dynload"/_tkinter*.so \
       "$PY_STAGE/include" "$PY_STAGE/share" 2>/dev/null || true

_step "Pruning dependencies"
# Every entry here is dead weight at runtime. Guarded by verify_stage.sh, which
# imports the full native surface after this runs.
rm -rf "$SITE/torch/include"                                      # C++ headers
# pip stays: it is how the user installs post-install components (speech-to-text
# and anything else kept out of the installer for licensing reasons).
rm -rf "$SITE/onnxruntime"/{transformers,quantization,tools}      # export/training helpers
# NOT litellm/proxy (27MB): litellm_logging imports integrations.gcs_bucket at
# module scope, which imports litellm.proxy._types, so plain `import litellm`
# needs it. Verified by verify_stage.sh, which is why the prunes are guarded.
rm -rf "$SITE/pyarrow"/{include,tests}
# Flight only. NOT libarrow_substrait/_dataset/_acero: pyarrow/lib.*.so links all
# three directly, so removing substrait breaks `import pyarrow` outright and
# cascades into lancedb, sentence-transformers and gliner.
rm -f "$SITE/pyarrow"/libarrow_flight*.dylib
find "$SITE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$SITE" -name '*.dist-info' -type d -exec rm -rf {}/RECORD \; 2>/dev/null || true

_step "Byte-compiling"
# unchecked-hash, not the default timestamp invalidation: ditto, DMG creation
# and notarization all rewrite mtimes, which would invalidate every .pyc and
# send a read-only bundle trying to rewrite them at import time.
"$PY" -m compileall -q -f -j 0 --invalidation-mode unchecked-hash \
    "$PY_STAGE/lib/python$PY_MINOR" >/dev/null 2>&1 || _warn "compileall reported errors (usually py2-only vendored files)"
[ -d "$STAGE/backend" ] && "$PY" -m compileall -q -f -j 0 --invalidation-mode unchecked-hash \
    "$STAGE/backend" >/dev/null 2>&1 || true

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
