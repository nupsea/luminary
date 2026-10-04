# Shared setup for every smoke script. Source it straight after `set -euo pipefail`:
#
#   source "$(dirname "$0")/lib.sh"
#
# LUMINARY_BASE_URL is the API base, and the only way a script learns it:
#   dev backend (full mode)   http://localhost:7820            (the default)
#   bundled app (public mode) http://127.0.0.1:<its port>/api
#
# scripts/check_smoke_paths.py enforces the conventions below in `make lint`.

SMOKE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SMOKE_DIR/../.." && pwd)"

BASE="${LUMINARY_BASE_URL:-http://localhost:7820}"
BASE="${BASE%/}"
export BASE

# Native Windows Python otherwise decodes pipes as cp1252.
export PYTHONUTF8=1

# all.sh counts this exit code as a skip, not a failure.
SMOKE_SKIP=77

# Under `set -e` a failed command exits with no message: a curl --max-time
# inside $(...) left only a bare [FAIL]. Name the command, line and exit code.
set -E
smoke_on_err() {
  local code=$1 hint=""
  [ "$code" -eq 28 ] && hint=" (curl: timed out)"
  echo "FAIL: exit $code$hint at $(basename "$2"):$3: $4" >&2
}
trap 'smoke_on_err $? "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND"' ERR

# One temp dir per run; write under $SMOKE_TMP or `mktemp`, never a literal /tmp,
# which native Windows Python cannot open. `cygpath -m` gives a C:/... all tools read.
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

# smoke_requires_internet: the backend fetches from a third party; SMOKE_OFFLINE=1 skips.
smoke_requires_internet() {
    if [ "${SMOKE_OFFLINE:-0}" = "1" ]; then
        echo "SKIP: fetches from a third-party site, and SMOKE_OFFLINE=1"
        exit "$SMOKE_SKIP"
    fi
}

# smoke_requires_repo_toolchain: the script runs the repo's own Python through uv rather
# than calling the server, so a machine with only the installed app skips it.
smoke_requires_repo_toolchain() {
    if ! command -v uv >/dev/null 2>&1; then
        echo "SKIP: runs the repo's Python through uv, which this machine does not have"
        exit "$SMOKE_SKIP"
    fi
}

# smoke_requires_local_model: skip when the server refuses local inference on its host
# and is in Local mode. The refusal itself is the product working; it is not a pass.
smoke_requires_local_model() {
    local refused mode
    refused="$(curl -sf --max-time 10 "$BASE/setup/host-support" | python3 -c \
        'import json, sys; d = json.load(sys.stdin); print("" if d.get("supported") else d.get("reason") or "refused")' \
        2>/dev/null || true)"
    [ -n "$refused" ] || return 0
    mode="$(curl -sf --max-time 10 "$BASE/settings/llm" | python3 -c \
        'import json, sys; print(json.load(sys.stdin).get("mode", ""))' 2>/dev/null || true)"
    if [ "$mode" = "private" ]; then
        echo "SKIP: this host refuses local inference ($refused) and the server is in Local mode"
        exit "$SMOKE_SKIP"
    fi
}

# smoke_wait_complete <document_id>: poll until stage=complete; fail on error or 404.
# Long deadline: ingestion queues behind earlier scripts' LLM calls (#142).
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

# smoke_openapi: the API schema, paths relative to $BASE. Served at the origin root,
# with /api-prefixed paths in public mode. Fetched once per run.
smoke_openapi() {
    local cache="$SMOKE_TMP/openapi.json" origin="${BASE%/api}" prefix=""
    [ "$origin" != "$BASE" ] && prefix="/api"
    if [ ! -s "$cache" ]; then
        # Git Bash otherwise rewrites the "/api" argv to "C:/Program Files/Git/api".
        curl -sf --max-time 60 "$origin/openapi.json" | MSYS_NO_PATHCONV=1 python3 -c '
import json, sys
spec, prefix = json.load(sys.stdin), sys.argv[1]
if prefix:
    spec["paths"] = {k[len(prefix):] if k.startswith(prefix + "/") else k: v
                     for k, v in spec.get("paths", {}).items()}
json.dump(spec, sys.stdout)' "$prefix" > "$cache" || { rm -f "$cache"; return 1; }
    fi
    cat "$cache"
}

# smoke_partial_skip <reason>: one sub-check did not run while the rest of the script
# did. all.sh reports it beside the pass, so a skipped check never reads as a pass (#187).
smoke_partial_skip() {
    echo "PARTIAL SKIP: $1"
    printf '%s: %s\n' "$(basename "$0" .sh)" "$1" >> "$SMOKE_TMP/.partial-skips"
}

# smoke_ingest_fixture: ingest a small two-section document, wait for it, and print its
# id. The caller deletes it on exit. A sub-check that needs a document gets this one,
# never whatever the library holds, so whether it runs does not depend on the machine (#221).
smoke_ingest_fixture() {
    local src="$SMOKE_TMP/fixture-$$-$RANDOM.md" out="$SMOKE_TMP/fixture-$$.json" code doc_id
    cat > "$src" <<'FIXTURE'
# Smoke fixture

## Write-ahead logging

A write-ahead log records every change before the change is applied to the data
file, so a crash between the two can be repaired by replaying the log on restart.
Readers keep reading the last committed state while a writer appends to the log.

## Checkpoints

A checkpoint copies the logged changes back into the data file and lets the log be
truncated. Without checkpoints the log grows without bound and recovery slows down,
because every change since the last checkpoint must be replayed.
FIXTURE
    # Ingest deduplicates on the file's hash; a unique line keeps each call its own document.
    printf '\nSmoke run %s.\n' "$$-$RANDOM" >> "$src"
    code="$(curl -s -o "$out" -w '%{http_code}' -X POST "$BASE/documents/ingest" \
        -F "file=@$src;type=text/markdown")"
    rm -f "$src"
    if [ "$code" != "200" ] && [ "$code" != "201" ]; then
        echo "FAIL: fixture upload got $code: $(cat "$out")" >&2
        return 1
    fi
    doc_id="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["document_id"])' "$out")"
    smoke_wait_complete "$doc_id" >&2 || {
        curl -s -o /dev/null -X DELETE "$BASE/documents/$doc_id" || true
        return 1
    }
    echo "$doc_id"
}
