#!/usr/bin/env bash
# Notarize a DMG and staple both it and the app.
#
#   scripts/macos/notarize.sh <dmg> <app>
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

DMG="${1:?usage: notarize.sh <dmg> <app>}"
APP="${2:?usage: notarize.sh <dmg> <app>}"
DIST="${DIST:-$BUILD_DIR/dist}"

: "${APPLE_API_KEY_PATH:?}" "${APPLE_API_KEY_ID:?}" "${APPLE_API_ISSUER:?}"
KEY_ARGS=(--key "$APPLE_API_KEY_PATH" --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER")

_step "Submitting to the notary service"
# Apple's scan time scales with file count, and this bundle has ~55k files.
xcrun notarytool submit "$DMG" "${KEY_ARGS[@]}" \
    --wait --timeout 45m --output-format json | tee "$DIST/notary.json"

SUBMISSION="$(python3 -c "import json;print(json.load(open('$DIST/notary.json'))['id'])")"
xcrun notarytool log "$SUBMISSION" "${KEY_ARGS[@]}" "$DIST/notary-log.json" || true

# `notarytool submit --wait` does not reliably exit non-zero on Invalid, so the
# status is asserted explicitly and the log is captured either way.
python3 - "$DIST/notary.json" "$DIST/notary-log.json" <<'PY'
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
# Both: the DMG so a download validates, and the app so it still validates
# offline once dragged out of the DMG. The ticket covers every nested cdhash,
# so one submission serves both.
xcrun stapler staple "$DMG"
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"

_step "Gatekeeper assessment"
# The end state that matters: what a user's Mac will conclude about a fresh
# download. Anything other than "Notarized Developer ID" means they still see a
# warning.
spctl --assess --type exec --verbose=4 "$APP"

_info "notarized and stapled: $DMG"
