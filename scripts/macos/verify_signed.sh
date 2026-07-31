#!/usr/bin/env bash
# Gates on a signed Luminary.app, run before spending a notarization round trip.
#
#   scripts/macos/verify_signed.sh <app> [--adhoc]
#
# Each check maps to a way this pipeline is known to break silently.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

APP="${1:?usage: verify_signed.sh <app> [--adhoc]}"
ADHOC="${2:-}"
FAILED=0
_fail() { printf '\033[1;31m  FAIL: %s\033[0m\n' "$*" >&2; FAILED=1; }
_pass() { printf '\033[1;32m  ok\033[0m   %s\n' "$*"; }

_step "1. Every Mach-O is signed and hardened"
# Enumeration is the fragile part: signing by extension misses python3.13,
# ollama and llama-server, and a partial fan-out failure leaves gaps that only
# surface as a notarization rejection or a dlopen abort on a user's machine.
n=0
while IFS= read -r -d '' f; do
    n=$((n + 1))
    out="$(codesign -dvvv "$f" 2>&1)" || { _fail "unsigned: $f"; continue; }
    grep -q 'flags=.*runtime' <<<"$out" || _fail "no hardened runtime: $f"
    if [ "$ADHOC" != "--adhoc" ]; then
        grep -q "TeamIdentifier=${APPLE_TEAM_ID:-}" <<<"$out" || _fail "wrong team: $f"
    fi
done < <(macho_files "$APP")
# A floor, not an inventory: it catches enumeration collapsing (a broken `file`
# pipeline yields a handful), not a dependency being added or removed.
[ "$n" -ge 300 ] || _fail "enumeration regressed: only $n Mach-O files found"
[ "$FAILED" = 0 ] && _pass "$n Mach-O files signed and hardened"

_step "2. Bundle signature verifies"
if codesign --verify --deep --strict --verbose=2 "$APP" 2>/dev/null; then
    _pass "codesign --verify --deep --strict"
else
    _fail "bundle signature does not verify"
fi

_step "3. Apple Silicon only"
bad=0
while IFS= read -r -d '' f; do
    lipo -archs "$f" 2>/dev/null | grep -q x86_64 && { _fail "x86_64 slice: $f"; bad=1; }
done < <(macho_files "$APP")
[ "$bad" = 0 ] && _pass "no x86_64 slices"

plist="$APP/Contents/Info.plist"
min="$(/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$plist" 2>/dev/null || echo '')"
[ "$min" = "14.0" ] && _pass "LSMinimumSystemVersion 14.0" \
    || _fail "LSMinimumSystemVersion is '$min', expected 14.0 (onnxruntime ships macosx_14_0_arm64 only)"

_step "4. Attribution ships"
# A licence obligation, so a hard failure rather than a checklist item.
for f in OLLAMA-LICENSE LLAMA.CPP-LICENSE; do
    [ -s "$APP/Contents/Resources/licenses/$f" ] && _pass "$f" || _fail "missing licences/$f"
done

_step "5. Nothing writes inside the bundle"
# The signature is the tripwire: any write breaks the seal. Boot the real
# server against a scratch DATA_DIR, then re-verify.
PY="$APP/Contents/Resources/python/bin/python$PY_MINOR"
D="$(mktemp -d)"
if [ -x "$PY" ]; then
    DATA_DIR="$D" LUMINARY_MODE=public LOG_LEVEL=WARNING \
        LUMINARY_APP_ROOT="$APP/Contents/Resources" \
        "$PY" -I -c "import app.main" >/dev/null 2>&1 \
        && _pass "app.main imports from the signed bundle" \
        || _fail "app.main does not import from the signed bundle"

    if codesign --verify --deep --strict "$APP" 2>/dev/null; then
        _pass "seal intact after running"
    else
        _fail "something wrote inside the bundle:"
        find "$APP" -newer "$APP/Contents/Info.plist" -type f 2>/dev/null | head -5 >&2
    fi
else
    _fail "no interpreter at $PY"
fi
rm -rf "$D"

_step "6. Gatekeeper assessment"
if [ "$ADHOC" = "--adhoc" ]; then
    _info "skipped: ad-hoc signatures are always rejected"
else
    if spctl --assess --type exec --verbose=4 "$APP" 2>&1 | grep -q accepted; then
        _pass "spctl accepts the bundle"
    else
        _warn "spctl rejects it — expected until the DMG is notarized and stapled"
    fi
fi

echo
[ "$FAILED" = 0 ] && printf '\033[1;32msignature verified\033[0m\n' \
                  || printf '\033[1;31msignature verification FAILED\033[0m\n'
exit "$FAILED"
