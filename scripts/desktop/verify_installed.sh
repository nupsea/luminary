#!/usr/bin/env bash
# Launch an installed Luminary the way a user does and wait for it to open.
#
#   scripts/desktop/verify_installed.sh <installed-executable> [deadline-seconds]
#
# Passes when the shell logs `ready`, the app stays up, and a document ingested
# through it is found by vector search (then deleted). SCREENSHOT=<file.png>
# captures the screen once ready (Linux needs ImageMagick's `import` and a display).
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

EXE="${1:?usage: verify_installed.sh <installed-executable> [deadline-seconds]}"
DEADLINE="${2:-600}"
SCREENSHOT="${SCREENSHOT:-}"
# On a fresh install the first ingest waits for setup to finish downloading the embedder.
INGEST_DEADLINE="${INGEST_DEADLINE:-600}"

# Kept in step with log_dir() in src-tauri/src/logging.rs.
case "$DESKTOP_OS" in
    macos) LOG_DIR="$HOME/Library/Logs/Luminary" ;;
    windows) LOG_DIR="$(cygpath -u "$LOCALAPPDATA")/Luminary/Logs" ;;
    linux) LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/luminary" ;;
    *) _die "no desktop bundle for $(uname -s)" ;;
esac
LOG="$LOG_DIR/luminary.log"
mkdir -p "$BUILD_DIR"

before=0
[ -f "$LOG" ] && before="$(wc -l < "$LOG")"
this_launch() { [ -f "$LOG" ] && tail -n +"$((before + 1))" "$LOG"; }

json_field() { sed -n "s/.*\"$1\":\"\([^\"]*\)\".*/\1/p"; }

# `ready` is only a connection; the first real Windows install passed it while every ingest failed.
check_ingest() {
    local backend api dir doc_id status stage waited
    backend="$(this_launch | sed -n 's/.*\[shell\] backend: \(http[^ ]*\).*/\1/p' | tail -1)"
    [ -n "$backend" ] || { _warn "the shell never logged its backend address"; return 1; }
    api="$backend/api"
    dir="$(mktemp -d)"
    # The mingw curl in Git Bash cannot open an MSYS path handed to it inside -F.
    command -v cygpath >/dev/null 2>&1 && dir="$(cygpath -m "$dir")"
    local token="install-check-$(date +%s)-$$"
    printf '%s\nThe quartermaster counted brass lanterns along the lighthouse stairs.\n' \
        "$token" > "$dir/install-check.txt"

    _step "Ingesting a document through $api"
    status="$(curl -s -m 120 -o "$dir/ingest.json" -w '%{http_code}' \
        -F "file=@$dir/install-check.txt;filename=$token.txt" "$api/documents/ingest")"
    doc_id="$(json_field document_id < "$dir/ingest.json")"
    if [ "$status" != 200 ] || [ -z "$doc_id" ]; then
        _warn "ingest returned HTTP $status: $(head -c 300 "$dir/ingest.json")"
        return 1
    fi

    stage=""
    for waited in $(seq 1 "$INGEST_DEADLINE"); do
        curl -s -m 10 "$api/documents/$doc_id/status" > "$dir/status.json" || true
        stage="$(json_field stage < "$dir/status.json")"
        case "$stage" in complete | error) break ;; esac
        sleep 1
    done

    local result=1
    local search="$api/search?q=brass%20lanterns%20lighthouse&document_id=$doc_id&strategy=vector&limit=5"
    case "$stage" in
        complete)
            if curl -s -m 120 "$search" | grep -q "$token"; then
                _info "ingested in ${waited}s and found by vector search"
                result=0
            else
                _warn "ingest completed in ${waited}s but vector search did not find the document"
            fi ;;
        error) _warn "ingest failed: $(json_field error_message < "$dir/status.json")" ;;
        *) _warn "ingest still '${stage:-unknown}' after ${INGEST_DEADLINE}s" ;;
    esac

    curl -s -m 30 -X DELETE "$api/documents/$doc_id" >/dev/null || _warn "could not delete $doc_id"
    rm -rf "$dir"
    return "$result"
}

_step "Launching $EXE"
"$EXE" >"$BUILD_DIR/installed-app.out" 2>&1 &
APP=$!

result="deadline"
for _ in $(seq 1 "$DEADLINE"); do
    lines="$(this_launch)"
    if grep -q '\[shell\] FAILED at' <<<"$lines"; then result="failed"; break; fi
    if grep -q '\[shell\] ready: ' <<<"$lines"; then result="ready"; break; fi
    kill -0 "$APP" 2>/dev/null || { result="exited"; break; }
    sleep 1
done

FAILED=0
case "$result" in
    ready)
        _info "the shell reported ready"
        if grep -q 'local model server unavailable' <<<"$lines"; then
            _warn "the bundled engine did not start"; FAILED=1
        fi
        # Long enough for a backend that dies after its first connection to be seen dying.
        sleep 20
        kill -0 "$APP" 2>/dev/null || { _warn "the app exited after reporting ready"; FAILED=1; }
        [ "$FAILED" = 0 ] && { check_ingest || FAILED=1; }
        ;;
    failed) _warn "the shell reported a startup failure"; FAILED=1 ;;
    exited) _warn "the app exited before it was ready"; FAILED=1 ;;
    deadline) _warn "not ready after ${DEADLINE}s"; FAILED=1 ;;
esac

if [ -n "$SCREENSHOT" ]; then
    case "$DESKTOP_OS" in
        linux) import -window root "$SCREENSHOT" 2>/dev/null ;;
        windows)
            SHOT="$(cygpath -w "$SCREENSHOT")" powershell.exe -NoProfile -Command '
                Add-Type -AssemblyName System.Windows.Forms, System.Drawing
                $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
                $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
                [System.Drawing.Graphics]::FromImage($bmp).CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
                $bmp.Save($env:SHOT)' ;;
        macos) screencapture -x "$SCREENSHOT" ;;
    esac
    [ -f "$SCREENSHOT" ] && _info "screenshot: $SCREENSHOT" || _warn "screenshot failed"
fi

_step "Stopping the app"
kill "$APP" 2>/dev/null
for _ in $(seq 1 30); do
    kill -0 "$APP" 2>/dev/null || break
    sleep 1
done
kill -0 "$APP" 2>/dev/null && { _warn "still running after 30s; killing"; kill -9 "$APP" 2>/dev/null; }

_step "This launch's log"
this_launch | tail -60 | sed 's/^/    /'

echo
[ "$FAILED" = 0 ] && printf '\033[1;32minstalled app opened\033[0m\n' || printf '\033[1;31minstalled app did NOT open\033[0m\n'
exit "$FAILED"
