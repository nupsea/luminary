# Shared by the desktop-bundle scripts on every platform. Source, don't execute.
# What ships is decided here once, so the three installers cannot drift apart.

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

# Pinned: bumping this changes every user's interpreter.
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

OLLAMA_VERSION="${OLLAMA_VERSION:-v0.32.5}"

# Stage budgets, enforced by verify_stage.sh, so a tool limit fails in our words.
# NSIS cannot pack past ~2048MB (a 2.28GB stage failed); Linux has no known ceiling.
case "$DESKTOP_OS" in
    windows) STAGE_SIZE_BUDGET_MB="${STAGE_SIZE_BUDGET_MB:-1900}" ;;
    *) STAGE_SIZE_BUDGET_MB="${STAGE_SIZE_BUDGET_MB:-}" ;;
esac

# Windows MAX_PATH 260 minus ~60 for the per-user install root. Checked on every OS:
# the dependency trees match and Linux CI is the cheaper signal.
STAGE_PATH_BUDGET="${STAGE_PATH_BUDGET:-190}"

_step() { printf '\n\033[1;36m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
_info() { printf '    %s\n' "$*"; }
_warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*" >&2; }
_die()  { printf '\033[1;31m  x %s\033[0m\n' "$*" >&2; exit 1; }

# Keep in step with PYTHON_BINARY in src-tauri/src/stage.rs.
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

# Git Bash shows /d/a/..., Windows programs write D:\a\...
native_path() {
    if [ "$DESKTOP_OS" = windows ]; then cygpath -w "$1"; else echo "$1"; fi
}

# `full` without `dev`; `media` stays out for its GPL codecs (docs/desktop-bundle.md).
# Keep in step with scripts/bootstrap.sh.
install_shipping_dependencies() {
    local py="$1"
    local req="$BUILD_DIR/requirements-app.txt"
    _step "Resolving the shipping dependency set"
    uv export --directory "$REPO_ROOT/backend" \
        --frozen --no-emit-project --no-default-groups --group full \
        --format requirements-txt --quiet -o "$req"
    _info "$(grep -cE '^[a-zA-Z0-9]' "$req") packages"

    _step "Installing dependencies into the staged interpreter"
    # `uv export` pins `torch==X+cpu` but drops the index it lives on; the exported
    # hashes still fix every file under unsafe-best-match.
    local index_args=()
    if [ "$DESKTOP_OS" != macos ]; then
        local cpu_index
        cpu_index="$("$py" - "$(native_path "$REPO_ROOT/backend/pyproject.toml")" <<'PYEOF'
import sys, tomllib
with open(sys.argv[1], "rb") as fh:
    indexes = tomllib.load(fh)["tool"]["uv"]["index"]
print(next(i["url"] for i in indexes if i["name"] == "pytorch-cpu"))
PYEOF
)" || _die "no pytorch-cpu index in backend/pyproject.toml"
        index_args=(--extra-index-url "$cpu_index" --index-strategy unsafe-best-match)
    fi
    # The +alternate form: bash 3.2 treats an empty array as unbound under set -u.
    uv pip sync --python "$py" --system ${index_args[@]+"${index_args[@]}"} "$req"
}

# Never add `testing`: `import torch` imports `torch.testing`.
prune_test_suites() {
    local site="$1" pruned=0 freed=0 sz d
    _step "Pruning bundled test suites"
    while IFS= read -r d; do
        sz=$(du -sk "$d" 2>/dev/null | cut -f1)
        rm -rf "$d" && pruned=$((pruned + 1)) && freed=$((freed + sz))
    done < <(find "$site" -type d \( -name tests -o -name test \) -prune -print 2>/dev/null)
    _info "removed $pruned test directories ($((freed / 1024)) MB)"
}

# A relative .pth line relocates with the bundle. `python -I` drops PYTHONPATH, so
# this is the only way the backend package is importable.
write_backend_pth() {
    local site="$1" rel
    _step "Putting the backend source on sys.path"
    [ -d "$site" ] || _die "site-packages not at $site"
    if [ "$DESKTOP_OS" = windows ]; then rel='../../../backend'; else rel='../../../../backend'; fi
    printf '%s\n' "$rel" > "$site/_luminary.pth"
}

# uv's absolute shebangs name the build machine's interpreter. Replace them with an
# sh/Python polyglot: sh runs the exec line, Python sees one string literal.
relocatable_shebangs() {
    local py="$1" bin_dir="$2"
    _step "Making console scripts relocatable"
    "$py" - "$bin_dir" <<'PYEOF'
import os, sys
bin_dir = sys.argv[1]
# The quoting is exact: a stray quote after `exec` breaks the sh side.
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

# Guarded by the verifiers, which import the full native surface afterwards.
prune_dependencies() {
    local site="$1"
    _step "Pruning dependencies"
    rm -rf "$site/torch/include"                                      # C++ headers
    # Build-time tools needing a Visual C++ runtime not shipped beside them
    # (verify_dll_imports.ps1). pip writes script wrappers with distlib's own launchers.
    rm -f "$site/torch/bin"/protoc* "$site/setuptools"/cli*.exe "$site/setuptools"/gui*.exe
    # pip stays: it installs post-install components.
    rm -rf "$site/onnxruntime"/{transformers,quantization,tools}      # export/training helpers
    # NOT litellm/proxy: plain `import litellm` reaches litellm.proxy._types.
    rm -rf "$site/pyarrow"/{include,tests}
    # Flight only, and all of it: a half-removed Flight leaves a dangling link that
    # fails linuxdeploy. NOT substrait/_dataset/_acero, which `import pyarrow` links.
    rm -f "$site/pyarrow"/libarrow_flight*.dylib "$site/pyarrow"/libarrow_flight.so* \
          "$site/pyarrow"/arrow_flight.dll \
          "$site/pyarrow"/libarrow_python_flight*.dylib \
          "$site/pyarrow"/libarrow_python_flight.so* \
          "$site/pyarrow"/arrow_python_flight.dll \
          "$site/pyarrow"/_flight.cpython-*.so "$site/pyarrow"/_flight*.pyd \
          "$site/pyarrow"/_flight.pyx "$site/pyarrow"/flight.py
    # The proxy admin UI build. NOT _experimental itself: guardrails imports it.
    rm -rf "$site/litellm/proxy/_experimental/out"
    # Benchmark fixtures holding the stage's longest paths (over STAGE_PATH_BUDGET).
    rm -rf "$site/litellm/proxy/guardrails/guardrail_hooks"/*/guardrail_benchmarks
    find "$site" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
    find "$site" -name '*.dist-info' -type d -exec rm -rf {}/RECORD \; 2>/dev/null || true
}

# Libraries that resolve their deps through a parent's inherited RPATH look broken
# to linuxdeploy, which inspects each ELF alone. Append the rpath the parent implied,
# searching only up to the stage root so host-owned deps stay with the host.
relink_bundled_libs() {
    local root="$1" lib dir need rpath target rel add new patched=0 examined=0
    [ "$DESKTOP_OS" = linux ] || return 0
    _step "Relinking libraries that rely on an inherited rpath"
    command -v patchelf >/dev/null 2>&1 || _die "patchelf is needed to stage on Linux"
    while IFS= read -r lib; do
        examined=$((examined + 1))
        dir="${lib%/*}"
        rpath="$(patchelf --print-rpath "$lib" 2>/dev/null)" || continue
        add=""
        while IFS= read -r need; do
            [ -n "$need" ] || continue
            target="$(_holding_dir "$dir" "$root" "$need")" || continue
            _rpath_covers "$dir" "$rpath$add" "$need" && continue
            rel="$(realpath --relative-to="$dir" "$target")"
            if [ "$rel" = "." ]; then
                add="$add:\$ORIGIN"
            else
                add="$add:\$ORIGIN/$rel"
            fi
        done < <(patchelf --print-needed "$lib" 2>/dev/null)
        [ -n "$add" ] || continue
        if [ -n "$rpath" ]; then
            new="$rpath$add"
        else
            new="${add#:}"
        fi
        # Keep a DT_RPATH a DT_RPATH: patchelf defaults to DT_RUNPATH, which is not inherited.
        if [ -n "$rpath" ] && objdump -p "$lib" 2>/dev/null | grep -q 'RPATH'; then
            patchelf --force-rpath --set-rpath "$new" "$lib"
        else
            patchelf --set-rpath "$new" "$lib"
        fi
        patched=$((patched + 1))
        _info "${lib#"$root"/}: rpath '$new'"
    done < <(find "$root" -type f \( -name '*.so' -o -name '*.so.*' \))
    _info "examined $examined libraries, relinked $patched"
}

# The directory holding $3, searched from $1 upwards but never above $2.
_holding_dir() {
    local dir="$1" root="$2" need="$3"
    while :; do
        if [ -e "$dir/$need" ]; then
            printf '%s\n' "$dir"
            return 0
        fi
        if [ "$dir" = "$root" ] || [ "$dir" = "${dir%/*}" ]; then
            return 1
        fi
        dir="${dir%/*}"
    done
}

# Whether $2 already names a directory holding $3, with $ORIGIN read against $1.
_rpath_covers() {
    local dir="$1" entry
    while IFS= read -r entry; do
        [ -n "$entry" ] || continue
        entry="${entry//\$\{ORIGIN\}/$dir}"
        entry="${entry//\$ORIGIN/$dir}"
        if [ -e "$entry/$3" ]; then
            return 0
        fi
    done < <(printf '%s\n' "${2//:/$'\n'}")
    return 1
}

# unchecked-hash: installers rewrite mtimes, which would invalidate timestamp .pycs.
byte_compile() {
    local py="$1"
    shift
    _step "Byte-compiling"
    "$py" -m compileall -q -f -j 0 --invalidation-mode unchecked-hash "$@" >/dev/null 2>&1 \
        || _warn "compileall reported errors (usually py2-only vendored files)"
}
