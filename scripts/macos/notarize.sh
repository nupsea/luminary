#!/usr/bin/env bash
# Notarize a DMG, staple it and the app, then emit the updater artifacts.
#
#   scripts/macos/notarize.sh <dmg> <app> <version>
#
# Requires an App Store Connect API key (APPLE_API_KEY_PATH, APPLE_API_KEY_ID,
# APPLE_API_ISSUER) rather than an app-specific password, which expires and
# cannot be scoped.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

DMG="${1:?usage: notarize.sh <dmg> <app> <version>}"
APP="${2:?usage: notarize.sh <dmg> <app> <version>}"
VERSION="${3:?usage: notarize.sh <dmg> <app> <version>}"
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
spctl --assess --type exec --verbose=4 "$APP"

_step "Updater artifacts"
# The tarball must contain the STAPLED app, or an updated install stops
# validating offline.
TARBALL="$DIST/Luminary_${VERSION}_aarch64.app.tar.gz"
tar -czf "$TARBALL" -C "$(dirname "$APP")" "$(basename "$APP")"

: "${TAURI_SIGNING_PRIVATE_KEY:?}"
"$REPO_ROOT/frontend/node_modules/.bin/tauri" signer sign \
    -f "$TAURI_SIGNING_PRIVATE_KEY" \
    -p "${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}" "$TARBALL"

python3 - "$VERSION" "$TARBALL" "$DIST/latest.json" "${GITHUB_REPOSITORY:-nupsea/luminary}" <<'PY'
import datetime, json, sys

version, tarball, out, repo = sys.argv[1:5]
signature = open(f"{tarball}.sig").read().strip()
# darwin-aarch64 only. lancedb publishes no macOS x86_64 wheel, so advertising
# an Intel target would hand those users a broken update.
json.dump(
    {
        "version": version,
        "notes": "See CHANGELOG.md",
        "pub_date": datetime.datetime.now(datetime.UTC).isoformat(),
        "platforms": {
            "darwin-aarch64": {
                "signature": signature,
                "url": f"https://github.com/{repo}/releases/download/v{version}/"
                       f"{tarball.rsplit('/', 1)[-1]}",
            }
        },
    },
    open(out, "w"),
    indent=2,
)
print(f"wrote {out}")
PY

_info "release artifacts in $DIST"
