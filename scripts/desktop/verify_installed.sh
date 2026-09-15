#!/usr/bin/env bash
# Launch an installed Luminary the way a user does and wait for it to open.
#
#   scripts/desktop/verify_installed.sh <installed-executable> [deadline-seconds]
#
# Passes when the shell logs `ready`, which it reaches only after both children
# were spawned and the backend accepted a connection, and the app is still
# running shortly after. Fails on the shell's failure line, on its warning that
# the bundled engine did not start, or when the app exits or the deadline passes
# first. SCREENSHOT=<file.png> captures the screen once it is ready (Linux needs
# ImageMagick's `import` and a display, e.g. under xvfb-run).
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

EXE="${1:?usage: verify_installed.sh <installed-executable> [deadline-seconds]}"
DEADLINE="${2:-600}"
SCREENSHOT="${SCREENSHOT:-}"

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
        # Long enough for the window to navigate to the library, and for a backend
        # that dies right after accepting its first connection to be seen dying.
        sleep 20
        kill -0 "$APP" 2>/dev/null || { _warn "the app exited after reporting ready"; FAILED=1; }
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
