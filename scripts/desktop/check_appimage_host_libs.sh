#!/usr/bin/env bash
# Fail when a host graphics driver cannot load against an AppImage's bundled libraries.
#
#   scripts/desktop/check_appimage_host_libs.sh <extracted-AppDir>
#
# Run it on the distro under test, with Mesa installed: CI runs it in containers of
# the newest ones, whose drivers need the newest symbols. It resolves each driver the
# way the AppImage's web process would, bundled directories first (I-62).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

APPDIR="$(realpath "${1:?usage: check_appimage_host_libs.sh <extracted-AppDir>}")"
[ -d "$APPDIR/usr/lib" ] || _die "$APPDIR is not an extracted AppImage (no usr/lib)"

# Kept in step with the LD_LIBRARY_PATH linuxdeploy's AppRun sets.
path=""
for dir in usr/lib usr/lib/x86_64-linux-gnu usr/lib64 lib lib/x86_64-linux-gnu lib64; do
    [ -d "$APPDIR/$dir" ] && path="${path:+$path:}$APPDIR/$dir"
done

distro="$(. /etc/os-release && echo "$PRETTY_NAME")"
_step "Host graphics drivers on $distro against $(basename "$APPDIR")"

drivers=()
for root in /usr/lib64 /usr/lib/x86_64-linux-gnu /usr/lib; do
    [ -d "$root" ] || continue
    while IFS= read -r f; do drivers+=("$f"); done < <(
        find "$root" -maxdepth 2 \( -type f -o -type l \) \( \
            -name 'libEGL*.so*' -o -name 'libGL*.so*' -o -name 'libgbm.so*' \
            -o -name 'libgallium*.so' -o -name 'libvulkan_*.so' -o -name 'libnvidia-egl*.so*' \
            -o -path '*/dri/*.so' -o -path '*/gbm/*.so' \) 2>/dev/null | sort -u)
done
# Measured nothing is not a pass.
[ "${#drivers[@]}" -gt 0 ] || _die "no graphics drivers found on $distro; install Mesa first"

failed=0
for f in "${drivers[@]}"; do
    problems="$(LD_LIBRARY_PATH="$path" ldd -r "$f" 2>&1 \
        | grep -E 'undefined symbol|not found' | sort -u || true)"
    if [ -n "$problems" ]; then
        _warn "$f cannot load with the bundled libraries first:"
        sed 's/^/      /' <<<"$problems" | head -8
        failed=1
    fi
done

[ "$failed" = 0 ] || _die "a bundled library shadows one the host's drivers need; add it to prune_appimage.sh"
_info "${#drivers[@]} drivers load cleanly"
