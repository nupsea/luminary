# Shared setup for every smoke script. Source it straight after `set -euo pipefail`:
#
#   source "$(dirname "$0")/lib.sh"
#
# LUMINARY_BASE_URL is the API base, and the only way a script learns it:
#   dev backend (full mode)   http://localhost:7820            (the default)
#   bundled app (public mode) http://127.0.0.1:<its port>/api
#
# scripts/check_smoke_paths.py fails `make lint` if a script does not source this,
# defines its own base, writes to a literal /tmp, or calls a surface public mode
# does not mount without `smoke_require_mode full`.

SMOKE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SMOKE_DIR/../.." && pwd)"

BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"
BASE="${BASE%/}"
# Exported so Python snippets read os.environ["BASE"] instead of restating it.
export BASE

# Native Windows Python decodes stdin and pipes as cp1252 without this, and every
# script that pipes JSON with a non-ASCII character into python3 fails there.
export PYTHONUTF8=1

# all.sh counts this exit code as a skip, not a failure.
SMOKE_SKIP=77

# One directory per run, created by all.sh and removed when it finishes; a script
# run on its own gets a fresh one under the system temp dir. TMPDIR points into it,
# so a bare `mktemp` lands there too. Write temp files under $SMOKE_TMP or through
# `mktemp`, never to a literal /tmp: on Git Bash /tmp is an MSYS path that native
# Windows Python cannot open when it appears inside a `python3 -c` string.
# `cygpath -m` gives C:/... instead, which bash, curl and Python all resolve.
if [ -z "${SMOKE_TMP:-}" ]; then
    SMOKE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/luminary-smoke.XXXXXX")"
    if command -v cygpath >/dev/null 2>&1; then
        SMOKE_TMP="$(cygpath -m "$SMOKE_TMP")"
    fi
    export SMOKE_TMP
fi
export TMPDIR="$SMOKE_TMP"

# smoke_server_mode: the mode /health reports, read once per run.
smoke_server_mode() {
    if [ -z "${SMOKE_SERVER_MODE:-}" ]; then
        SMOKE_SERVER_MODE="$(curl -sf --max-time 10 "$BASE/health" \
            | python3 -c 'import json, sys; print(json.load(sys.stdin).get("mode", ""))' \
            2>/dev/null || true)"
        export SMOKE_SERVER_MODE
    fi
    printf '%s' "$SMOKE_SERVER_MODE"
}

# smoke_requires_internet: this script makes the backend fetch from a third-party
# site. SMOKE_OFFLINE=1 skips it, for a machine whose network must not see that
# traffic; the backend itself contacts no third party unless asked (I-18, I-57).
smoke_requires_internet() {
    if [ "${SMOKE_OFFLINE:-0}" = "1" ]; then
        echo "SKIP: fetches from a third-party site, and SMOKE_OFFLINE=1"
        exit "$SMOKE_SKIP"
    fi
}

# smoke_wait_complete <document_id>: poll until ingestion reaches stage=complete.
# Fails at once on stage=error or a document the backend no longer has. The
# deadline is long because ingestion makes background LLM calls that queue behind
# earlier scripts' summaries on the one serving slot, so its duration depends on
# what ran before it, not on the document (#142). SMOKE_INGEST_TIMEOUT overrides.
smoke_wait_complete() {
    local doc_id="$1" limit="${SMOKE_INGEST_TIMEOUT:-600}" elapsed=0 code stage=""
    while [ "$elapsed" -lt "$limit" ]; do
        sleep 5
        elapsed=$((elapsed + 5))
        code="$(curl -s -o "$SMOKE_TMP/wait_$doc_id.json" -w '%{http_code}' \
            "$BASE/documents/$doc_id" || true)"
        if [ "$code" = "404" ]; then
            echo "FAIL: document $doc_id is gone (404) while waiting for ingestion"
            return 1
        fi
        stage="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("stage", ""))' \
            "$SMOKE_TMP/wait_$doc_id.json" 2>/dev/null || true)"
        echo "  stage=${stage} (${elapsed}s)"
        case "$stage" in
            complete) return 0 ;;
            error) echo "FAIL: ingestion of $doc_id ended in stage=error"; return 1 ;;
        esac
    done
    echo "FAIL: $doc_id did not reach stage=complete within ${limit}s (last stage: ${stage})"
    return 1
}

# smoke_require_mode <full|public>: skip this script on a server in the other mode.
# An unreachable server is a failure, never a skip.
smoke_require_mode() {
    local have
    have="$(smoke_server_mode)"
    if [ -z "$have" ]; then
        echo "FAIL: no mode from $BASE/health (is the backend up?)"
        exit 1
    fi
    if [ "$have" != "$1" ]; then
        echo "SKIP: needs a $1-mode server; $BASE is $have"
        exit "$SMOKE_SKIP"
    fi
}
