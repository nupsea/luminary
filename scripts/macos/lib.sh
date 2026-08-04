# Shared helpers for the macOS desktop-bundle scripts. Source, don't execute.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$REPO_ROOT/build}"
STAGE="${STAGE:-$BUILD_DIR/stage}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$BUILD_DIR/pythons}"

# Pinned deliberately. Bumping this changes every user's interpreter and
# invalidates the CI cache key, so it is a reviewed decision, not a floating range.
PBS_VERSION="${PBS_VERSION:-cpython-3.13.7-macos-aarch64-none}"
PY_MINOR="3.13"

# Pinned Ollama release. `ollama` spawns lib/ollama/llama-server, so the whole
# tree ships, not just the driver binary.
OLLAMA_VERSION="${OLLAMA_VERSION:-v0.32.5}"

_step() { printf '\n\033[1;36m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
_info() { printf '    %s\n' "$*"; }
_warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*" >&2; }
_die()  { printf '\033[1;31m  x %s\033[0m\n' "$*" >&2; exit 1; }

staged_python() { echo "$STAGE/python/bin/python$PY_MINOR"; }

# Emit NUL-separated paths of every Mach-O file under $1.
#
# Enumerating by extension is the classic mistake here: `-name '*.so' -o -name
# '*.dylib'` silently misses python3.13, ollama and llama-server, which are
# extensionless. Ask `file` what things actually are, in one batched pass --
# per-file `-exec file` over ~55k files is minutes of fork overhead.
# A universal binary yields one line PER SLICE, each suffixed with
# " (for architecture arm64)", so the path must be recovered and deduped --
# otherwise every fat .so comes back as a nonexistent path.
macho_files() {
    find "$1" -type f ! -type l -print0 \
        | xargs -0 file --mime-type -h 2>/dev/null \
        | awk '/application\/x-mach-binary/ {
                 sub(/:[ \t]+[a-z]+\/[a-z0-9.+-]+$/, "");   # separator is space OR tab
                 sub(/ \(for architecture [^)]*\)$/, "");
                 print
               }' \
        | sort -u | tr '\n' '\0'
}
