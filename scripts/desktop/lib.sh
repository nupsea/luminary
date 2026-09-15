# Shared by the desktop-bundle scripts on every platform. Source, don't execute.
#
# `scripts/macos/` sources this and adds what only a signed Mac bundle needs.
# Everything that decides WHAT ships -- the dependency profile, the prunes, the
# import check in verify_imports.py -- lives here once, so the three installers
# cannot drift into shipping different apps.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$REPO_ROOT/build}"
STAGE="${STAGE:-$BUILD_DIR/stage}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$BUILD_DIR/pythons}"

case "$(uname -s)" in
    Darwin) DESKTOP_OS=macos ;;
    Linux) DESKTOP_OS=linux ;;
    MINGW* | MSYS* | CYGWIN*) DESKTOP_OS=windows ;;
    *) DESKTOP_OS=unsupported ;;
esac

# Pinned deliberately. Bumping this changes every user's interpreter and
# invalidates the CI cache keys, so it is a reviewed decision, not a floating range.
PY_MINOR="3.13"
PY_RELEASE="3.13.7"
case "$DESKTOP_OS" in
    macos) _pbs_platform="macos-aarch64-none" ;;
    # gnu, not musl: the Linux wheels in uv.lock are manylinux.
    linux) _pbs_platform="linux-x86_64-gnu" ;;
    windows) _pbs_platform="windows-x86_64-none" ;;
    *) _pbs_platform="unsupported" ;;
esac
PBS_VERSION="${PBS_VERSION:-cpython-$PY_RELEASE-$_pbs_platform}"

# Pinned Ollama release, the same on every platform.
OLLAMA_VERSION="${OLLAMA_VERSION:-v0.32.5}"

_step() { printf '\n\033[1;36m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
_info() { printf '    %s\n' "$*"; }
_warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*" >&2; }
_die()  { printf '\033[1;31m  x %s\033[0m\n' "$*" >&2; exit 1; }

# python-build-standalone lays Windows out flat (python.exe, Lib/) and unix
# under bin/ and lib/pythonX.Y/. Kept in step with PYTHON_BINARY in
# src-tauri/src/stage.rs.
staged_python() {
    if [ "$DESKTOP_OS" = windows ]; then
        echo "$STAGE/python/python.exe"
    else
        echo "$STAGE/python/bin/python$PY_MINOR"
    fi
}

staged_stdlib() {
    if [ "$DESKTOP_OS" = windows ]; then
        echo "$STAGE/python/Lib"
    else
        echo "$STAGE/python/lib/python$PY_MINOR"
    fi
}

staged_site() { echo "$(staged_stdlib)/site-packages"; }

# A path as native programs on this host spell it. Git Bash shows /d/a/...,
# while a Windows program writes D:\a\... into what it produces, so anything
# looking for a build-machine path has to look for both.
native_path() {
    if [ "$DESKTOP_OS" = windows ]; then cygpath -w "$1"; else echo "$1"; fi
}

# The shipping profile: no `dev` (Phoenix, pytest, ruff, tiktoken, reportlab --
# ~120MB that no user ever runs) but yes `full`, because the desktop app
# advertises YouTube and web ingestion and must actually support it. `media`
# stays out: its wheels carry GPL codecs (docs/desktop-bundle.md).
# Keep in step with scripts/bootstrap.sh, which installs the same profile.
install_shipping_dependencies() {
    local py="$1"
    local req="$BUILD_DIR/requirements-app.txt"
    _step "Resolving the shipping dependency set"
    uv export --directory "$REPO_ROOT/backend" \
        --frozen --no-emit-project --no-default-groups --group full \
        --format requirements-txt --quiet -o "$req"
    _info "$(grep -cE '^[a-zA-Z0-9]' "$req") packages"

    _step "Installing dependencies into the staged interpreter"
    # --system because this is not a venv: it is a private interpreter we own.
    uv pip sync --python "$py" --system "$req"
}

# Third-party test suites are never executed from the bundle. `testing` is NOT
# in this list and must not be: `import torch` imports `torch.testing`, so
# removing it breaks the interpreter this ships. Only directories literally
# named `test`/`tests` go.
prune_test_suites() {
    local site="$1" pruned=0 freed=0 sz d
    _step "Pruning bundled test suites"
    while IFS= read -r d; do
        sz=$(du -sk "$d" 2>/dev/null | cut -f1)
        rm -rf "$d" && pruned=$((pruned + 1)) && freed=$((freed + sz))
    done < <(find "$site" -type d \( -name tests -o -name test \) -prune -print 2>/dev/null)
    _info "removed $pruned test directories ($((freed / 1024)) MB)"
}

# site.addpackage joins each .pth line against the site dir, so a RELATIVE line
# relocates with the bundle. It climbs to the stage root, where stage_payload.sh
# puts backend/: four levels from lib/pythonX.Y/site-packages, three from
# Windows' Lib/site-packages. The app launches with `python -I`, which drops
# PYTHONPATH, so this .pth is the only way the backend package is importable.
write_backend_pth() {
    local site="$1" rel
    _step "Putting the backend source on sys.path"
    [ -d "$site" ] || _die "site-packages not at $site"
    if [ "$DESKTOP_OS" = windows ]; then rel='../../../backend'; else rel='../../../../backend'; fi
    printf '%s\n' "$rel" > "$site/_luminary.pth"
}

# uv writes unix console scripts with an absolute shebang naming the build
# machine's interpreter, which is dead on a user's machine -- and bin/ is on the
# backend's PATH, so a dead script there is found and then fails. Rewrite the
# shebang as the sh/Python polyglot trampoline: sh runs the exec line, Python
# sees one string literal.
relocatable_shebangs() {
    local py="$1" bin_dir="$2"
    _step "Making console scripts relocatable"
    "$py" - "$bin_dir" <<'PYEOF'
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
}

# Every entry here is dead weight at runtime. Guarded by the verifiers, which
# import the full native surface after this runs.
prune_dependencies() {
    local site="$1"
    _step "Pruning dependencies"
    rm -rf "$site/torch/include"                                      # C++ headers
    # pip stays: it is how the user installs post-install components (speech-to-text
    # and anything else kept out of the installer for licensing reasons).
    rm -rf "$site/onnxruntime"/{transformers,quantization,tools}      # export/training helpers
    # NOT litellm/proxy (27MB): litellm_logging imports integrations.gcs_bucket at
    # module scope, which imports litellm.proxy._types, so plain `import litellm`
    # needs it.
    rm -rf "$site/pyarrow"/{include,tests}
    # Flight only. NOT libarrow_substrait/_dataset/_acero: pyarrow's lib extension
    # links all three directly, so removing substrait breaks `import pyarrow`
    # outright and cascades into lancedb, sentence-transformers and gliner.
    rm -f "$site/pyarrow"/libarrow_flight*.dylib "$site/pyarrow"/libarrow_flight.so* \
          "$site/pyarrow"/arrow_flight.dll
    find "$site" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
    find "$site" -name '*.dist-info' -type d -exec rm -rf {}/RECORD \; 2>/dev/null || true
}

# unchecked-hash, not the default timestamp invalidation: copying into a bundle
# or an installer rewrites mtimes, which would invalidate every .pyc and send a
# read-only install trying to rewrite them at import time.
byte_compile() {
    local py="$1"
    shift
    _step "Byte-compiling"
    "$py" -m compileall -q -f -j 0 --invalidation-mode unchecked-hash "$@" >/dev/null 2>&1 \
        || _warn "compileall reported errors (usually py2-only vendored files)"
}
