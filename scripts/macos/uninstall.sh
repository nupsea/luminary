#!/usr/bin/env bash
# Remove the Luminary desktop app.
#
#   bash scripts/macos/uninstall.sh
#
# Self-contained on purpose: someone uninstalling has no reason to still have a
# checkout, so this must run standalone.
#
# This is the DMG install only. If you installed with bootstrap.sh, use
# `luminary uninstall` instead -- that one also unregisters the login service,
# and its library lives somewhere else entirely.
set -euo pipefail

APP="/Applications/Luminary.app"
DATA_DIR="$HOME/Library/Application Support/sh.luminary.app"
LOG_DIR="$HOME/Library/Logs/Luminary"
CACHE_DIR="$HOME/Library/Caches/sh.luminary.app"
SAVED_STATE="$HOME/Library/Saved Application State/sh.luminary.app.savedState"

_info() { printf '%s\n' "$*"; }

if pgrep -f "Luminary.app/Contents/MacOS/luminary-desktop" >/dev/null 2>&1; then
    _info "Quitting Luminary..."
    osascript -e 'quit app "Luminary"' 2>/dev/null || true
    # Give the shell time to stop its own children; it kills its process group
    # on exit, so this is what leaves nothing behind.
    sleep 3
    pkill -f "Luminary.app/Contents/MacOS/luminary-desktop" 2>/dev/null || true
fi

if [ -d "$APP" ]; then
    rm -rf "$APP"
    _info "Removed $APP"
else
    _info "No app at $APP"
fi

rm -rf "$LOG_DIR" "$CACHE_DIR" "$SAVED_STATE"
_info "Removed logs and caches."

# The library holds every document, note, flashcard and review the user has
# created. Never delete it without an explicit typed confirmation, and default
# to keeping it -- an uninstall is not consent to destroy data.
if [ -d "$DATA_DIR" ]; then
    SIZE="$(du -sh "$DATA_DIR" 2>/dev/null | cut -f1)"
    _info ""
    _info "Your library is still at:"
    _info "  $DATA_DIR ($SIZE)"
    _info "It holds every document, note, flashcard and review you have created,"
    _info "and the downloaded models."
    _info ""
    if [ -t 0 ]; then
        printf 'Delete it permanently? Type DELETE to confirm, anything else to keep: '
        read -r REPLY
        if [ "$REPLY" = "DELETE" ]; then
            rm -rf "$DATA_DIR"
            _info "Library deleted."
        else
            _info "Library kept."
        fi
    else
        _info "Not running interactively -- library kept."
        _info "Remove it yourself with:  rm -rf \"$DATA_DIR\""
    fi
fi

_info ""
_info "Done."
