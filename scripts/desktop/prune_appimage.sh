#!/usr/bin/env bash
# Remove the libraries that belong to the host from a built AppImage, in place.
#
#   scripts/desktop/prune_appimage.sh <file.AppImage>
#
# The AppImage puts its usr/lib ahead of the system's on the library path, and the
# host's Mesa is loaded from the system. Bundled libwayland 1.20 (Ubuntu 22.04) lacks
# symbols Mesa 26 needs, so its EGL failed to load and WebKit's web process aborted:
# a blank window on Fedora 44 and Bluefin. tauri's pinned linuxdeploy ignores
# LINUXDEPLOY_EXCLUDED_LIBRARIES, so the exclusion happens here.
# check_appimage_host_libs.sh is the gate for anything this list misses.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

IMAGE="$(realpath "${1:?usage: prune_appimage.sh <file.AppImage>}")"

# Graphics and driver libraries: every host that can draw a window has its own,
# built against its own Mesa and drivers.
HOST_OWNED=(
    libwayland-client.so.0 libwayland-cursor.so.0 libwayland-egl.so.1 libwayland-server.so.0
    libvulkan.so.1 libcuda.so.1 libnvidia-ml.so.1
)

for tool in unsquashfs mksquashfs; do
    command -v "$tool" >/dev/null || _die "$tool is missing (apt install squashfs-tools)"
done

# The runtime is an ELF whose section headers end where the squashfs begins; this is
# how the runtime finds it too.
elf_field() { od -An -t "u$2" -j "$1" -N "$2" "$IMAGE" | tr -d " "; }
offset=$(( $(elf_field 40 8) + $(elf_field 58 2) * $(elf_field 60 2) ))
[[ "$offset" =~ ^[0-9]+$ ]] || _die "could not read the runtime's size from $IMAGE: $offset"
info="$(unsquashfs -s -o "$offset" "$IMAGE")"
comp="$(sed -n 's/^Compression \([a-z0-9]*\).*/\1/p' <<<"$info")"
block="$(sed -n 's/^Block size \([0-9]*\).*/\1/p' <<<"$info")"
[ -n "$comp" ] && [ -n "$block" ] || _die "could not read the squashfs header of $IMAGE"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
_step "Unpacking $(basename "$IMAGE") (runtime ${offset} bytes, $comp, ${block}-byte blocks)"
unsquashfs -q -n -o "$offset" -d "$work/AppDir" "$IMAGE"
head -c "$offset" "$IMAGE" > "$work/runtime"

# The directories AppRun puts on LD_LIBRARY_PATH. The staged app under usr/lib/Luminary
# is not among them and keeps what it ships.
removed=0
for dir in usr/lib usr/lib/x86_64-linux-gnu usr/lib64 lib lib/x86_64-linux-gnu lib64; do
    for lib in "${HOST_OWNED[@]}"; do
        if [ -e "$work/AppDir/$dir/$lib" ] || [ -L "$work/AppDir/$dir/$lib" ]; then
            rm -f "$work/AppDir/$dir/$lib"
            _info "removed $dir/$lib"
            removed=$((removed + 1))
        fi
    done
done
[ "$removed" -gt 0 ] || _info "none of the host-owned libraries were bundled"

_step "Repacking"
mksquashfs "$work/AppDir" "$work/image.squashfs" -root-owned -noappend -quiet \
    -comp "$comp" -b "$block" >/dev/null
cat "$work/runtime" "$work/image.squashfs" > "$work/out.AppImage"
chmod 755 "$work/out.AppImage"
mv -f "$work/out.AppImage" "$IMAGE"
_info "$(basename "$IMAGE"): $(( $(stat -c %s "$IMAGE") / 1048576 ))MB, $removed libraries removed"
