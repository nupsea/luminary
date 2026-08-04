#!/usr/bin/env bash
# Sign Luminary.app inside-out.
#
#   scripts/macos/sign.sh <app> [--adhoc]
#
# --adhoc signs with the ad-hoc identity, which exercises enumeration, ordering
# and the verification gates without a certificate. Ad-hoc signatures are not
# notarizable and Gatekeeper rejects them; they exist so the pipeline can be
# tested before credentials are provisioned.
#
# Tauri's own signer is deliberately unused: it runs `codesign --deep`, which
# applies one entitlement set to every nested binary. The interpreter and the
# outer app need different ones, and Apple documents --deep as a repair tool
# rather than a way to sign.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

APP="${1:?usage: sign.sh <app> [--adhoc]}"
MODE="${2:-}"
ENT_APP="$REPO_ROOT/src-tauri/entitlements.plist"
ENT_PY="$REPO_ROOT/src-tauri/entitlements-python.plist"

[ -d "$APP" ] || _die "no app bundle at $APP"

if [ "$MODE" = "--adhoc" ]; then
    IDENTITY="-"
    _warn "ad-hoc signing: not notarizable, and Gatekeeper will reject it"
else
    IDENTITY="${APPLE_SIGNING_IDENTITY:?set APPLE_SIGNING_IDENTITY or pass --adhoc}"
fi

_step "Pre-sign hygiene"
# Extended attributes and AppleDouble files make codesign fail late and
# obscurely; strip them before anything is signed.
xattr -cr "$APP"
find "$APP" \( -name '._*' -o -name '.DS_Store' \) -delete 2>/dev/null || true

_step "Signing nested Mach-O files"
count=0
tmp="$(mktemp)"
macho_files "$APP/Contents/Resources" | tr '\0' '\n' > "$tmp"
count=$(wc -l < "$tmp" | tr -d ' ')
_info "$count binaries"

# xargs in parallel: this is ~900MB of native code and the dominant cost of the
# whole release. --timestamp needs a network round trip per call, so ad-hoc mode
# skips it (the ad-hoc identity cannot be timestamped anyway).
TS_FLAG="--timestamp"
[ "$IDENTITY" = "-" ] && TS_FLAG=""
# shellcheck disable=SC2086
tr '\n' '\0' < "$tmp" | xargs -0 -n 16 -P "$(sysctl -n hw.ncpu)" \
    codesign --force $TS_FLAG --options runtime \
             --entitlements "$ENT_PY" --sign "$IDENTITY"
rm -f "$tmp"

_step "Signing the interpreter with a pinned identifier"
# Keychain ACLs bind to the designated requirement, which embeds this
# identifier. settings_service stores API keys through keyring; if the
# identifier were derived from the filename, a future layout change would
# rotate it and every user's stored keys would become unreachable. Frozen.
# shellcheck disable=SC2086
codesign --force $TS_FLAG --options runtime \
         --identifier sh.luminary.app.python \
         --entitlements "$ENT_PY" --sign "$IDENTITY" \
         "$APP/Contents/Resources/python/bin/python$PY_MINOR"

_step "Signing the inference server"
for b in ollama llama-server; do
    target="$APP/Contents/Resources/ollama/$b"
    [ -f "$target" ] || continue
    # shellcheck disable=SC2086
    codesign --force $TS_FLAG --options runtime \
             --identifier "sh.luminary.app.$b" --sign "$IDENTITY" "$target"
done

_step "Sealing the bundle"
# Last, so the seal covers everything above.
# shellcheck disable=SC2086
codesign --force $TS_FLAG --options runtime \
         --entitlements "$ENT_APP" --sign "$IDENTITY" "$APP"

_step "Verifying"
codesign --verify --deep --strict --verbose=2 "$APP"
_info "signed $count nested binaries plus the bundle"
