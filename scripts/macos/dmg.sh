#!/usr/bin/env bash
# Build Luminary.dmg from a signed .app.
#
#   scripts/macos/dmg.sh <app> <version> [--adhoc]
#
# hdiutil rather than create-dmg: one less thing to install on a runner, and
# the window styling create-dmg exists for needs AppleScript and a GUI session.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

APP="${1:?usage: dmg.sh <app> <version> [--adhoc]}"
VERSION="${2:?usage: dmg.sh <app> <version> [--adhoc]}"
MODE="${3:-}"
DIST="${DIST:-$BUILD_DIR/dist}"
DMG="$DIST/Luminary_${VERSION}_aarch64.dmg"

[ -d "$APP" ] || _die "no app bundle at $APP"
mkdir -p "$DIST"
rm -f "$DMG"

_step "Staging the disk image"
STAGE_DMG="$(mktemp -d)/Luminary"
mkdir -p "$STAGE_DMG"
ditto "$APP" "$STAGE_DMG/$(basename "$APP")"
ln -s /Applications "$STAGE_DMG/Applications"

_step "Building $DMG"
# ULFO (LZFSE) over UDZO: smaller and faster to decompress on this payload.
hdiutil create -volname "Luminary" -srcfolder "$STAGE_DMG" \
    -ov -format ULFO -quiet "$DMG"
rm -rf "$(dirname "$STAGE_DMG")"

if [ "$MODE" = "--adhoc" ]; then
    codesign --force --sign - "$DMG"
else
    codesign --force --timestamp --sign "${APPLE_SIGNING_IDENTITY:?}" "$DMG"
fi

_info "$(du -h "$DMG" | awk '{print $1}')  $DMG"
echo "$DMG"
