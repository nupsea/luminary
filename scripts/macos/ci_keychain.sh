#!/usr/bin/env bash
# Import the Developer ID certificate into a throwaway CI keychain.
#
# Reads APPLE_CERTIFICATE (base64 .p12), APPLE_CERTIFICATE_PASSWORD and
# KEYCHAIN_PASSWORD from the environment. Used by both the build and the
# notarize job -- the second needs the identity to sign the DMG.
#
# `-T` seeds the key's ACL and set-key-partition-list allows non-interactive
# use: without them codesign blocks on a UI prompt no runner can answer.
set -euo pipefail

: "${APPLE_CERTIFICATE:?}" "${APPLE_CERTIFICATE_PASSWORD:?}" "${KEYCHAIN_PASSWORD:?}"

KC="$RUNNER_TEMP/build.keychain"
P12="$RUNNER_TEMP/cert.p12"

echo "$APPLE_CERTIFICATE" | base64 --decode > "$P12"
trap 'rm -f "$P12"' EXIT

security create-keychain -p "$KEYCHAIN_PASSWORD" "$KC"
security set-keychain-settings -lut 21600 "$KC"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KC"
security import "$P12" -k "$KC" -P "$APPLE_CERTIFICATE_PASSWORD" \
    -T /usr/bin/codesign -T /usr/bin/security
security set-key-partition-list -S apple-tool:,apple:,codesign: \
    -s -k "$KEYCHAIN_PASSWORD" "$KC"
security list-keychain -d user -s "$KC" login.keychain

# `find-identity` exits 0 even when it finds nothing, so assert explicitly.
if ! security find-identity -v -p codesigning "$KC" | grep -q "1 valid identities found"; then
    echo "no usable codesigning identity in $KC" >&2
    security find-identity -v -p codesigning "$KC" >&2
    exit 1
fi
security find-identity -v -p codesigning "$KC"
