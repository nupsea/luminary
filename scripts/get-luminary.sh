#!/usr/bin/env bash
# get-luminary.sh -- install the Luminary desktop app on Linux in one command.
#
#   curl -fsSL https://raw.githubusercontent.com/nupsea/luminary/master/scripts/get-luminary.sh | bash
#
# Debian/Ubuntu get the .deb through apt, which resolves WebKitGTK and asks for
# sudo once. Everything else gets the AppImage in ~/.local with a menu entry and
# a `luminary` command. Both verify the download against the release's .sha256
# and open the app, whose first-run setup fetches the models.
#
# LUMINARY_VERSION=0.13.2   a specific release instead of the latest
# LUMINARY_FORMAT=appimage  skip apt even where it exists (deb|appimage|auto)
# LUMINARY_INSTALLER=<file> install a local .deb/.AppImage, no download
# LUMINARY_NO_LAUNCH=1      install without opening the app
set -euo pipefail

REPO="${LUMINARY_REPO:-nupsea/luminary}"
VERSION="${LUMINARY_VERSION:-latest}"
FORMAT="${LUMINARY_FORMAT:-auto}"
PREFIX="${LUMINARY_PREFIX:-$HOME/.local}"
# The AppImage is built on Ubuntu 22.04 and runs only on a glibc this new or newer.
MIN_GLIBC="2.35"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Linux ] || die "this installer is for Linux; see the README for your system"
[ "$(uname -m)" = x86_64 ] || die "Luminary is built for x86_64 only (this is $(uname -m))"
command -v curl >/dev/null || die "curl is required"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

as_root() {
    if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi
}

can_use_apt() {
    command -v apt-get >/dev/null && command -v dpkg >/dev/null || return 1
    [ "$(id -u)" = 0 ] || command -v sudo >/dev/null
}

glibc_ok() {
    local have
    have="$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')"
    [ -n "$have" ] && [ "$(printf '%s\n%s\n' "$MIN_GLIBC" "$have" | sort -V | head -1)" = "$MIN_GLIBC" ]
}

release_json() {
    if [ -n "${LUMINARY_RELEASE_JSON:-}" ]; then
        cat "$LUMINARY_RELEASE_JSON"
        return
    fi
    local url="https://api.github.com/repos/$REPO/releases/latest"
    [ "$VERSION" = latest ] || url="https://api.github.com/repos/$REPO/releases/tags/v${VERSION#v}"
    curl -fsSL -H "Accept: application/vnd.github+json" "$url" \
        || die "could not read release '$VERSION' of $REPO"
}

# The download URL of the release asset whose name ends in $1.
asset_url() {
    grep -o '"browser_download_url": *"[^"]*"' "$WORK/release.json" \
        | sed -e 's/^"browser_download_url": *"//' -e 's/"$//' \
        | grep -E "Luminary_[^/]*$(printf '%s' "$1" | sed 's/\./\\./g')\$" \
        | head -1
}

# Download the asset ending in $1 and its .sha256; refuse a mismatch.
fetch_verified() {
    local url sum_url file expected actual
    url="$(asset_url "$1")"
    [ -n "$url" ] || die "release '$VERSION' has no *$1 -- it may predate Linux installers"
    sum_url="$(asset_url "$1.sha256")"
    [ -n "$sum_url" ] || die "release '$VERSION' has no checksum for *$1; refusing to install unverified"
    file="$WORK/${url##*/}"
    say "Downloading ${url##*/}" >&2
    curl -fL --progress-bar -o "$file" "$url" || die "download failed: $url"
    expected="$(curl -fsSL "$sum_url" | awk '{print $1}')"
    actual="$(sha256sum "$file" | awk '{print $1}')"
    [ -n "$expected" ] && [ "$expected" = "$actual" ] \
        || die "checksum mismatch for ${file##*/} (expected ${expected:-nothing}, got $actual)"
    printf '%s\n' "$file"
}

launch() {
    [ "${LUMINARY_NO_LAUNCH:-0}" = 1 ] && return
    if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
        say "No desktop session here; open Luminary from your applications menu."
        return
    fi
    say "Opening Luminary. First launch downloads its models and takes a few minutes."
    setsid -f "$@" >/dev/null 2>&1 </dev/null || true
}

install_deb() {
    local deb="$1" pkg exe
    say "Installing $(basename "$deb") with apt (asks for your password once)"
    as_root apt-get install -y "$deb" || die "apt could not install $(basename "$deb")"
    pkg="$(dpkg-deb -f "$deb" Package)"
    exe="$(dpkg -L "$pkg" | grep '^/usr/bin/' | head -1)"
    [ -n "$exe" ] || die "$pkg installed but no executable was found in /usr/bin"
    say "Installed. Remove with: sudo apt remove $pkg"
    launch "$exe"
}

install_appimage() {
    local image="$1" dir="$PREFIX/lib/luminary" apps="$PREFIX/share/applications"
    local target="$dir/Luminary.AppImage" bin="$PREFIX/bin/luminary" icon=""
    glibc_ok || die "this system's glibc is older than $MIN_GLIBC, which the AppImage needs"
    mkdir -p "$dir" "$apps" "$PREFIX/bin"
    cp "$image" "$target.new" && chmod +x "$target.new" && mv -f "$target.new" "$target"

    # Without libfuse2 an AppImage cannot mount itself; extract-and-run is the
    # same program unpacked to /tmp first, and the shell ends with it.
    local env_prefix=""
    if ! ldconfig -p 2>/dev/null | grep -q 'libfuse\.so\.2'; then
        env_prefix="env APPIMAGE_EXTRACT_AND_RUN=1 "
        say "libfuse2 not found: Luminary will unpack itself on each launch (slower start)"
    fi

    # The top-level icon is a symlink into usr/share/icons, so extract both.
    (cd "$WORK" && "$target" --appimage-extract '*.png' >/dev/null 2>&1 \
        && "$target" --appimage-extract 'usr/share/icons/*' >/dev/null 2>&1) || true
    local png
    png="$(find "$WORK/squashfs-root" -maxdepth 1 -name '*.png' 2>/dev/null | head -1)" || true
    if [ -n "$png" ] && cp -L "$png" "$dir/luminary.png" 2>/dev/null; then
        icon="$dir/luminary.png"
    fi

    cat > "$bin" <<EOF
#!/bin/sh
exec ${env_prefix}"$target" "\$@"
EOF
    chmod +x "$bin"
    cat > "$apps/luminary.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Luminary
Comment=Local-first learning cockpit
Exec=$bin
Icon=${icon:-$target}
Terminal=false
Categories=Education;Office;
EOF
    command -v update-desktop-database >/dev/null && update-desktop-database "$apps" 2>/dev/null || true
    say "Installed to $dir. Remove with: rm -rf '$dir' '$bin' '$apps/luminary.desktop'"
    case ":$PATH:" in *":$PREFIX/bin:"*) ;; *) say "Add $PREFIX/bin to PATH to run 'luminary' from a terminal." ;; esac
    launch "$bin"
}

case "$FORMAT" in
    auto) if can_use_apt; then FORMAT=deb; else FORMAT=appimage; fi ;;
    deb | appimage) ;;
    *) die "LUMINARY_FORMAT must be deb, appimage or auto (got '$FORMAT')" ;;
esac
[ "$FORMAT" = deb ] && ! can_use_apt && die "the .deb needs apt-get and sudo; try LUMINARY_FORMAT=appimage"

if [ -n "${LUMINARY_INSTALLER:-}" ]; then
    [ -f "$LUMINARY_INSTALLER" ] || die "no such file: $LUMINARY_INSTALLER"
    file="$(cd "$(dirname "$LUMINARY_INSTALLER")" && pwd)/$(basename "$LUMINARY_INSTALLER")"
else
    release_json > "$WORK/release.json"
    if [ "$FORMAT" = deb ]; then
        file="$(fetch_verified _amd64.deb)"
    else
        file="$(fetch_verified _amd64.AppImage)"
    fi
fi

if [ "$FORMAT" = deb ]; then install_deb "$file"; else install_appimage "$file"; fi
