# Helpers for the macOS desktop-bundle scripts. Source, don't execute.
#
# Paths, pins and the steps that decide what ships come from
# scripts/desktop/lib.sh, shared with the Windows and Linux installers. Only what
# a signed Mac bundle needs on top of that lives here.

source "$(dirname "${BASH_SOURCE[0]}")/../desktop/lib.sh"

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
