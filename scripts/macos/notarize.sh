#!/usr/bin/env bash
# Notarize one artifact and staple its ticket.
#
#   scripts/macos/notarize.sh <app-or-dmg>
#
# Run it twice per release: on the .app before dmg.sh packages it, then on the
# DMG. A ticket only attaches to the artifact that was submitted, so an app
# packaged before it is stapled reaches users without one and needs a network
# round trip to Apple on first launch.
#
# Requires an App Store Connect API key (APPLE_API_KEY_PATH, APPLE_API_KEY_ID,
# APPLE_API_ISSUER) rather than an app-specific password, which expires and
# cannot be scoped.
#
# Distribution is a downloaded DMG. There is no auto-updater: the plugin is not
# a dependency and no public key is configured, so publishing update artifacts
# would ship something nothing can consume.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

TARGET="${1:?usage: notarize.sh <app-or-dmg>}"
DIST="${DIST:-$BUILD_DIR/dist}"

[ -e "$TARGET" ] || _die "no artifact at $TARGET"
mkdir -p "$DIST"

: "${APPLE_API_KEY_PATH:?}" "${APPLE_API_KEY_ID:?}" "${APPLE_API_ISSUER:?}"
KEY_ARGS=(--key "$APPLE_API_KEY_PATH" --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER")

NAME="$(basename "$TARGET")"
SLUG="${NAME%.*}"
JSON="$DIST/notary-${SLUG}.json"
LOG="$DIST/notary-log-${SLUG}.json"

# notarytool takes a zip, dmg or pkg, never a bare bundle. A compressed image
# rather than `ditto -c -k`: the same payload as a zip ran past 45 minutes at
# Apple and was still In Progress at 60, while the image form completes in ~20.
SUBMIT="$TARGET"
TMPDIR_PKG=""
if [ -d "$TARGET" ]; then
    TMPDIR_PKG="$(mktemp -d)"
    SUBMIT="$TMPDIR_PKG/${SLUG}-notarize.dmg"
    hdiutil create -volname "$SLUG" -srcfolder "$TARGET" \
        -ov -format ULFO -quiet "$SUBMIT"
fi

_step "Submitting $NAME to the notary service"
# Apple's scan time scales with file count, and this bundle has ~55k files.
xcrun notarytool submit "$SUBMIT" "${KEY_ARGS[@]}" \
    --wait --timeout 90m --output-format json | tee "$JSON"

if [ -n "$TMPDIR_PKG" ]; then
    rm -rf "$TMPDIR_PKG"
fi

SUBMISSION="$(python3 -c "import json;print(json.load(open('$JSON'))['id'])")"
xcrun notarytool log "$SUBMISSION" "${KEY_ARGS[@]}" "$LOG" || true

# `notarytool submit --wait` does not reliably exit non-zero on Invalid, so the
# status is asserted explicitly and the log is captured either way.
python3 - "$JSON" "$LOG" <<'PY'
import json, sys

status = json.load(open(sys.argv[1])).get("status")
if status != "Accepted":
    print(f"notarization status: {status}", file=sys.stderr)
    try:
        for issue in json.load(open(sys.argv[2])).get("issues") or []:
            print(f"  {issue.get('severity')} {issue.get('path')}: {issue.get('message')}",
                  file=sys.stderr)
    except Exception:
        pass
    sys.exit(1)
print("notarization accepted")
PY

_step "Stapling"
xcrun stapler staple "$TARGET"
xcrun stapler validate "$TARGET"

_step "Gatekeeper assessment"
# The end state that matters: what a user's Mac will conclude about a fresh
# download. Anything other than "Notarized Developer ID" means they still see a
# warning.
if [ -d "$TARGET" ]; then
    spctl --assess --type exec --verbose=4 "$TARGET"
else
    spctl --assess --type open --context context:primary-signature --verbose=4 "$TARGET"
fi

_info "notarized and stapled: $TARGET"
