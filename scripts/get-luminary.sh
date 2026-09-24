#!/usr/bin/env bash
# get-luminary.sh -- install or remove the Luminary desktop app on Linux in one command.
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
# LUMINARY_INSTALL_ANYWAY=1 install on a host that cannot run local models, without asking
# LUMINARY_UNINSTALL=1      remove the app; your library is kept, with the commands to delete it
# LUMINARY_REUSE_MODELS=1   reuse your own Ollama's models without asking (0: never)
# LUMINARY_ALLOW_DOWNGRADE=1 install an older version over a newer one
#
# A failure saves a report and, if the user agrees, opens it as an email to the
# developer. Everything runs from `main` on the last line, so a download cut short
# under `curl | bash` runs nothing.
set -Eeuo pipefail

REPO="${LUMINARY_REPO:-nupsea/luminary}"
VERSION="${LUMINARY_VERSION:-latest}"
FORMAT="${LUMINARY_FORMAT:-auto}"
PREFIX="${LUMINARY_PREFIX:-$HOME/.local}"
ACTION=install
[ "${LUMINARY_UNINSTALL:-0}" = 1 ] && ACTION=uninstall
REPORT_TO="eanups@yahoo.com"
RELEASES="https://github.com/$REPO/releases"
# Where the app keeps its library and log (Tauri's app_local_data_dir, logging.rs).
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/sh.luminary.app"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/luminary"
MODELS_DIR="$DATA_DIR/ollama/models"
# The Ollama tags model_registry.REGISTRY measures, which are the ones worth reusing
# from a user's own Ollama. test_get_luminary_script.py fails when they drift.
KNOWN_MODELS="llama3.2 qwen3.5:4b phi4-mini gemma3:4b qwen2.5vl:7b qwen2.5:14b-instruct"
# The AppImage is built on Ubuntu 22.04 and runs only on a glibc this new or newer.
MIN_GLIBC="2.35"
# Measured on 0.13.2: the .deb unpacks to 2.07 GB, the AppImage is 0.62 GB, and the
# largest download is the 0.67 GB .deb. 2 GB free fails partway through apt.
NEED_DEB_MB=2560
NEED_APPIMAGE_MB=1024
NEED_DOWNLOAD_MB=1024
# The host checks and message are host_support.local_inference_support's, so a
# refused machine hears it before the download rather than after.
# test_get_luminary_script.py fails when they drift.
MIN_RAM_GB=16
UNSUPPORTED_MESSAGE="This system isn't supported for running local models at a usable speed. Reading, search, notes and your learner record all work as normal. For answers and flashcards, add your own API key in Settings — or wait for the hosted version of Luminary, which is coming soon."
# Tests point this at a fake /dev and /proc.
SYSROOT="${LUMINARY_SYSROOT:-}"
WORK=""
TARGET_VERSION=""
LAUNCH_CMD=""
KEPT=""

log() { [ -z "$WORK" ] || printf '%s\n' "$*" >> "$WORK/steps.log" 2>/dev/null || true; }
say() { printf '\033[1m==>\033[0m %s\n' "$*"; log "==> $*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; log "warning: $*"; }

# Recorded for the exit trap, which offers the report from the main shell even when
# this runs inside $(...).
die() {
    printf '\033[1;31merror:\033[0m %s\n' "$*" >&2
    log "error: $*"
    if [ -n "$WORK" ] && [ ! -e "$WORK/failure" ]; then printf '%s\n' "$*" > "$WORK/failure"; fi
    exit 1
}

# A refusal the user can act on: said plainly, with no report offered.
refuse() {
    [ -z "$WORK" ] || : > "$WORK/declined"
    die "$@"
}

has_tty() { (: </dev/tty) 2>/dev/null; }

on_error() {
    [ -z "$WORK" ] || [ -e "$WORK/failure" ] || printf 'unexpected failure at line %s: %s\n' "$1" "$2" > "$WORK/failure"
}

on_exit() {
    local status=$?
    trap - ERR
    if [ "$status" -ne 0 ] && [ -n "$WORK" ] && [ ! -e "$WORK/declined" ]; then
        report || true
    fi
    [ -z "$WORK" ] || rm -rf "$WORK"
    exit "$status"
}

as_root() {
    if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi
}

can_use_apt() {
    command -v apt-get >/dev/null && command -v dpkg >/dev/null || return 1
    [ "$(id -u)" = 0 ] || command -v sudo >/dev/null
}

glibc_ok() {
    local have
    have="$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')" || true
    [ -n "$have" ] || refuse "this system does not use glibc (Alpine and other musl systems cannot run the AppImage)"
    [ "$(printf '%s\n%s\n' "$MIN_GLIBC" "$have" | sort -V | head -1)" = "$MIN_GLIBC" ]
}

has_accelerator() {
    case "${CUDA_VISIBLE_DEVICES:-}" in "" | -1) ;; *) return 0 ;; esac
    local node
    for node in /dev/nvidiactl /proc/driver/nvidia/version /dev/kfd; do
        [ -e "$SYSROOT$node" ] && return 0
    done
    compgen -G "$SYSROOT/dev/nvidia[0-9]*" >/dev/null
}

# Rounded up (I-56); 0 when unreadable, which is not a refusal on its own.
ram_gb() {
    local kb
    kb="$(awk '/^MemTotal:/ {print $2; exit}' "$SYSROOT/proc/meminfo" 2>/dev/null)" || true
    echo $(( (${kb:-0} + 1048575) / 1048576 ))
}

check_host() {
    local declared why="" ram answer=""
    declared="$(printf %s "${LUMINARY_HOST_SUPPORTED:-}" | tr "[:upper:]" "[:lower:]")"
    case "$declared" in 1 | true | yes) return ;; esac
    if ! has_accelerator; then
        why="no NVIDIA or AMD graphics card was found"
    else
        ram="$(ram_gb)"
        if [ "$ram" -gt 0 ] && [ "$ram" -lt "$MIN_RAM_GB" ]; then
            why="this machine has ${ram}GB of memory; local models need ${MIN_RAM_GB}GB"
        fi
    fi
    [ -z "$why" ] && return
    printf '\n%s\n(%s)\n\n' "$UNSUPPORTED_MESSAGE" "$why" >&2
    if [ "${LUMINARY_INSTALL_ANYWAY:-0}" = 1 ]; then
        say "Installing anyway for reading, search and notes"
        return
    fi
    # Under `curl | bash` stdin is this script, so the answer comes from the terminal.
    if has_tty; then
        printf 'Install anyway for reading, search and notes? [y/N] ' >&2
        read -r answer </dev/tty || true
    fi
    case "$answer" in [yY] | [yY][eE][sS]) return ;; esac
    refuse "not installed. To install for reading, search and notes, run again with LUMINARY_INSTALL_ANYWAY=1"
}

# Free MB on the filesystem holding $1, or its nearest existing parent; empty when unreadable.
free_mb() {
    local dir="$1"
    while [ ! -d "$dir" ] && [ "$dir" != / ] && [ "$dir" != . ]; do dir="$(dirname "$dir")"; done
    df -Pm "$dir" 2>/dev/null | awk 'NR == 2 {print $4}' || true
}

need_space() {
    local have
    have="$(free_mb "$1")"
    [ -n "$have" ] || return 0
    [ "$have" -ge "$2" ] \
        || refuse "only $have MB is free in $1; $3 needs about $2 MB. Free some space and run this again."
}

# A sentence for one of curl's exit codes.
curl_why() {
    case "$1" in
        6) echo "the server's name could not be looked up; check your internet connection" ;;
        7) echo "could not connect; check your internet connection or proxy" ;;
        22) echo "the server refused the request" ;;
        23) echo "the download could not be written; the disk may be full" ;;
        28) echo "the connection timed out" ;;
        35 | 51 | 58 | 60 | 77) echo "no secure connection could be made; something on your network may be intercepting HTTPS" ;;
        18 | 56) echo "the connection was interrupted" ;;
        *) echo "curl exit code $1" ;;
    esac
}

CURL=(curl --retry 3 --retry-delay 2 --connect-timeout 20)

release_json() {
    if [ -n "${LUMINARY_RELEASE_JSON:-}" ]; then
        cp "$LUMINARY_RELEASE_JSON" "$WORK/release.json" || die "cannot read $LUMINARY_RELEASE_JSON"
        return
    fi
    local url="https://api.github.com/repos/$REPO/releases/latest" code rc=0
    [ "$VERSION" = latest ] || url="https://api.github.com/repos/$REPO/releases/tags/v${VERSION#v}"
    code="$("${CURL[@]}" -sSL -H "Accept: application/vnd.github+json" \
        -o "$WORK/release.json" -w '%{http_code}' "$url")" || rc=$?
    [ "$rc" = 0 ] || die "could not reach GitHub for the release list: $(curl_why "$rc")"
    case "$code" in
        200) ;;
        404)
            [ "$VERSION" = latest ] && die "$REPO has no published release"
            refuse "there is no Luminary release v${VERSION#v}; the releases are listed at $RELEASES"
            ;;
        403 | 429) refuse "GitHub refused the request (HTTP $code), usually its hourly limit for your network; try again in an hour" ;;
        *) die "GitHub answered HTTP $code for $url" ;;
    esac
}

# The download URL of the release asset whose name ends in $1.
asset_url() {
    grep -o '"browser_download_url": *"[^"]*"' "$WORK/release.json" \
        | sed -e 's/^"browser_download_url": *"//' -e 's/"$//' \
        | grep -E "Luminary_[^/]*$(printf '%s' "$1" | sed 's/\./\\./g')\$" \
        | head -1 || true
}

sha256_of() {
    if command -v sha256sum >/dev/null; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null; then
        shasum -a 256 "$1" | awk '{print $1}'
    elif command -v openssl >/dev/null; then
        openssl dgst -sha256 -r "$1" | awk '{print $1}'
    else
        die "no SHA-256 tool (sha256sum, shasum or openssl) to verify the download with"
    fi
}

# Download the asset ending in $1 and its .sha256; refuse a mismatch.
fetch_verified() {
    local url sum_url file expected actual rc=0
    url="$(asset_url "$1")"
    [ -n "$url" ] || refuse "release '$VERSION' has no *$1 -- it may predate Linux installers"
    sum_url="$(asset_url "$1.sha256")"
    [ -n "$sum_url" ] || die "release '$VERSION' has no checksum for *$1; refusing to install unverified"
    need_space "$WORK" "$NEED_DOWNLOAD_MB" "the download"
    file="$WORK/${url##*/}"
    say "Downloading ${url##*/}" >&2
    "${CURL[@]}" -fL --progress-bar -o "$file" "$url" || rc=$?
    [ "$rc" = 0 ] || die "could not download ${url##*/}: $(curl_why "$rc")"
    [ -s "$file" ] || die "the download of ${url##*/} is empty"
    expected="$("${CURL[@]}" -fsSL "$sum_url" | awk '{print $1}')" \
        || die "could not download the checksum ${sum_url##*/}"
    actual="$(sha256_of "$file")"
    [ -n "$expected" ] && [ "$expected" = "$actual" ] \
        || die "checksum mismatch for ${file##*/} (expected ${expected:-nothing}, got $actual). The download was corrupted or altered, and nothing was installed. Run this again; if it repeats, something on your network is changing downloads."
    printf '%s\n' "$file"
}

# Pids of Luminary's own processes, matched by executable path and never by name, so a
# user's own `ollama serve` survives. $1 is `app` (the window) or `helpers` (the
# backend and engine a crash can leave behind).
luminary_pids() {
    local p exe kind
    for p in /proc/[0-9]*; do
        exe="$(readlink "$p/exe" 2>/dev/null)" || continue
        case "$exe" in
            */usr/bin/luminary-desktop | "$PREFIX/lib/luminary/Luminary.AppImage") kind=app ;;
            */usr/lib/Luminary/* | "$DATA_DIR/engine/"*) kind=helpers ;;
            *) continue ;;
        esac
        if [ "$kind" = "$1" ]; then echo "${p#/proc/}"; fi
    done
}

stop_leftovers() {
    local pids
    pids="$(luminary_pids app)"
    [ -z "$pids" ] || refuse "Luminary is running. Close it, then run this again; your library is kept."
    pids="$(luminary_pids helpers)"
    [ -n "$pids" ] || return 0
    say "Stopping Luminary's background processes left from an earlier run"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    for _ in 1 2 3 4 5; do
        [ -n "$(luminary_pids helpers)" ] || return 0
        sleep 1
    done
    # shellcheck disable=SC2046
    kill -9 $(luminary_pids helpers) 2>/dev/null || true
}

# The package that owns the .deb's executable, when the .deb is installed.
deb_package() {
    command -v dpkg-query >/dev/null || return 0
    dpkg-query -S /usr/bin/luminary-desktop 2>/dev/null | cut -d: -f1 | head -1 || true
}

# The installed version: the .deb's, else the one install_appimage recorded.
installed_version() {
    local pkg v=""
    pkg="$(deb_package)"
    if [ -n "$pkg" ]; then
        v="$(dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null)" || v=""
    elif [ -r "$PREFIX/lib/luminary/VERSION" ]; then
        v="$(head -1 "$PREFIX/lib/luminary/VERSION")"
    fi
    printf '%s' "${v%%[-+~]*}"
}

# The version inside a local installer: the .deb's control field, else its file name.
file_version() {
    local v=""
    case "$1" in *.deb) v="$(dpkg-deb -f "$1" Version 2>/dev/null)" || v="" ;; esac
    [ -n "$v" ] || v="$(basename "$1" | sed -n 's/^Luminary_\([0-9][0-9.]*[0-9]\)_.*/\1/p')"
    printf '%s' "${v%%[-+~]*}"
}

# An older app does not know a newer one's migrations, so it may not open the library.
check_version() {
    local new="${1#v}" old
    old="$(installed_version)"
    [ -n "$new" ] && [ -n "$old" ] || return 0
    if [ "$old" = "$new" ]; then
        say "Luminary $old is already installed; installing it again"
    elif [ "$(printf '%s\n%s\n' "$old" "$new" | sort -V | tail -1)" = "$new" ]; then
        say "Upgrading Luminary $old to $new"
    elif [ "${LUMINARY_ALLOW_DOWNGRADE:-0}" = 1 ]; then
        warn "replacing Luminary $old with the older $new"
    else
        refuse "Luminary $old is installed and $new is older. An older version may not open a library that a newer one has upgraded. To install it anyway, run this again with LUMINARY_ALLOW_DOWNGRADE=1"
    fi
}

# A user's own Ollama is named, never touched: Luminary's runs on a private port with
# its own models folder, so the two share only the graphics card's memory.
user_ollama_running() {
    local p exe
    if command -v systemctl >/dev/null && systemctl is-active --quiet ollama 2>/dev/null; then return 0; fi
    for p in /proc/[0-9]*; do
        exe="$(readlink "$p/exe" 2>/dev/null)" || continue
        case "$exe" in
            */usr/lib/Luminary/* | "$DATA_DIR/engine/"*) ;;
            */ollama) return 0 ;;
        esac
    done
    return 1
}

# Where a user's Ollama keeps models: OLLAMA_MODELS, a user install, and the home of
# the system service that Ollama's installer and the distribution packages create.
ollama_stores() {
    local s own
    own="$(cd "$MODELS_DIR" 2>/dev/null && pwd -P)" || own=""
    for s in "${OLLAMA_MODELS:-}" "$HOME/.ollama/models" /usr/share/ollama/.ollama/models \
             /var/lib/ollama/.ollama/models /var/lib/ollama/models; do
        [ -n "$s" ] && [ -d "$s/manifests" ] && [ -d "$s/blobs" ] || continue
        s="$(cd "$s" 2>/dev/null && pwd -P)" || continue
        if [ "$s" != "$own" ]; then printf '%s\n' "$s"; fi
    done | awk '!seen[$0]++'
}

manifest_rel() {
    local name="${1%%:*}" tag=latest
    case "$1" in *:*) tag="${1#*:}" ;; esac
    printf 'manifests/registry.ollama.ai/library/%s/%s' "$name" "$tag"
}

manifest_digests() {
    grep -o '"digest" *: *"sha256:[0-9a-f]\{64\}"' "$1" 2>/dev/null | grep -o '[0-9a-f]\{64\}' | sort -u || true
}

# Bytes of model $1's blobs in store $2; fails unless the manifest and every blob are readable.
model_bytes() {
    local rel d total=0 size digests
    rel="$(manifest_rel "$1")"
    [ -r "$2/$rel" ] || return 1
    digests="$(manifest_digests "$2/$rel")"
    [ -n "$digests" ] || return 1
    for d in $digests; do
        [ -r "$2/blobs/sha256-$d" ] || return 1
        size="$(stat -c %s "$2/blobs/sha256-$d" 2>/dev/null)" || return 1
        total=$((total + size))
    done
    printf '%s' "$total"
}

# A hard link shares the bytes and leaves the user's file as it was; a copy is the
# fallback where a link is refused (another filesystem, or another user's file). Each
# blob is checked against its digest before the manifest makes the model visible.
reuse_model() {
    local tag="$1" store="$2" rel d src dst have need added=() why=""
    rel="$(manifest_rel "$tag")"
    mkdir -p "$MODELS_DIR/blobs" "$(dirname "$MODELS_DIR/$rel")" || { warn "could not create $MODELS_DIR"; return 1; }
    say "Reusing $tag from $store"
    for d in $(manifest_digests "$store/$rel"); do
        src="$store/blobs/sha256-$d"
        dst="$MODELS_DIR/blobs/sha256-$d"
        [ -e "$dst" ] && continue
        rm -f "$dst.partial"
        if ! ln "$src" "$dst.partial" 2>/dev/null; then
            have="$(free_mb "$MODELS_DIR")"
            need=$(( $(stat -c %s "$src") / 1048576 + 512 ))
            if [ -n "$have" ] && [ "$have" -lt "$need" ]; then why="there is not enough free space to copy it"; break; fi
            cp "$src" "$dst.partial" || { why="it could not be copied"; break; }
        fi
        if [ "$(sha256_of "$dst.partial")" != "$d" ]; then why="it does not match its checksum in your Ollama"; break; fi
        mv -f "$dst.partial" "$dst" || { why="it could not be moved into place"; break; }
        added+=("$dst")
    done
    if [ -z "$why" ]; then
        { cp "$store/$rel" "$MODELS_DIR/$rel.partial" && mv -f "$MODELS_DIR/$rel.partial" "$MODELS_DIR/$rel"; } && return 0
        why="its manifest could not be copied"
    fi
    # Only this run's links and copies go; the user's own files are other names for the bytes.
    rm -f -- "$MODELS_DIR/$rel.partial" "${dst:-}.partial" ${added[@]+"${added[@]}"}
    warn "$tag was not reused: $why. Luminary downloads its own copy instead"
    return 1
}

offer_model_reuse() {
    local stores store tag bytes found="" answer="${LUMINARY_REUSE_MODELS:-}"
    [ "$answer" != 0 ] || return 0
    command -v sha256sum >/dev/null || command -v shasum >/dev/null || command -v openssl >/dev/null || return 0
    stores="$(ollama_stores)"
    [ -n "$stores" ] || return 0
    for tag in $KNOWN_MODELS; do
        [ ! -e "$MODELS_DIR/$(manifest_rel "$tag")" ] || continue
        while IFS= read -r store; do
            if bytes="$(model_bytes "$tag" "$store")"; then
                found+="$tag"$'\t'"$store"$'\t'"$bytes"$'\n'
                break
            fi
        done <<< "$stores"
    done
    [ -n "$found" ] || return 0
    say "Your Ollama already has models Luminary uses:"
    while IFS=$'\t' read -r tag store bytes; do
        [ -z "$tag" ] || printf '      %s (%s MB)\n' "$tag" "$((bytes / 1048576))"
    done <<< "$found"
    if [ "$answer" != 1 ]; then
        if ! has_tty; then
            say "To use them rather than download them again, run this again with LUMINARY_REUSE_MODELS=1."
            return 0
        fi
        printf 'Use them rather than download them again? Your Ollama and its models are not changed. [Y/n] ' >&2
        read -r answer </dev/tty || true
        case "$answer" in
            [nN] | [nN][oO]) say "Not reused; Luminary downloads its own."; return 0 ;;
        esac
    fi
    while IFS=$'\t' read -r tag store bytes; do
        [ -z "$tag" ] || reuse_model "$tag" "$store" || true
    done <<< "$found"
}

note_user_ollama() {
    local bin running=""
    bin="$(command -v ollama 2>/dev/null)" || bin=""
    if user_ollama_running; then running=1; fi
    [ -n "$bin$running" ] || [ -n "$(ollama_stores)" ] || return 0
    say "Found your own Ollama${bin:+ at $bin}. Luminary runs its own copy, on a private port with its own models folder, and leaves yours as it is."
    [ -z "$running" ] || warn "your Ollama is running. While both hold a model they share the graphics card's memory and both slow down; if answers are slow, stop yours while you use Luminary."
    offer_model_reuse
}

launch() {
    [ "${LUMINARY_NO_LAUNCH:-0}" = 1 ] && return
    if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
        say "No desktop session here; open Luminary from your applications menu."
        return
    fi
    say "Opening Luminary. First launch downloads its models and takes a few minutes."
    if command -v setsid >/dev/null; then
        setsid -f "$@" >/dev/null 2>&1 </dev/null || warn "could not open Luminary; open it from your applications menu"
    else
        nohup "$@" >/dev/null 2>&1 </dev/null &
    fi
}

install_deb() {
    local deb="$1" pkg exe
    need_space /usr "$NEED_DEB_MB" "the .deb"
    pkg="$(dpkg-deb -f "$deb" Package 2>/dev/null)" || die "$(basename "$deb") is not a readable .deb package"
    # apt reads the file as its sandbox user `_apt`, which cannot enter a 0700 temp dir.
    case "$deb" in "$WORK"/*) chmod 755 "$WORK" && chmod 644 "$deb" || true ;; esac
    say "Installing $(basename "$deb") with apt (asks for your password once)"
    if ! as_root apt-get install -y -o DPkg::Lock::Timeout=300 "$deb" </dev/null 2>&1 | tee -a "$WORK/steps.log"; then
        grep -q 'dpkg --configure -a' "$WORK/steps.log" \
            && die "an earlier package install was interrupted; run 'sudo dpkg --configure -a', then run this again"
        die "apt could not install $(basename "$deb"); its messages are above"
    fi
    exe="$(dpkg -L "$pkg" | grep '^/usr/bin/' | head -1)" || true
    [ -n "$exe" ] || die "$pkg installed but no executable was found in /usr/bin"
    say "Installed. To remove it, run this again with LUMINARY_UNINSTALL=1; your library is kept."
    [ ! -e "$PREFIX/lib/luminary/Luminary.AppImage" ] \
        || say "The AppImage build is installed too, so your menu lists Luminary twice; both open the same library."
    LAUNCH_CMD="$exe"
}

has_libfuse2() {
    { ldconfig -p 2>/dev/null || /sbin/ldconfig -p 2>/dev/null; } | grep -q 'libfuse\.so\.2'
}

install_appimage() {
    local image="$1" dir="$PREFIX/lib/luminary" apps="$PREFIX/share/applications"
    local target="$PREFIX/lib/luminary/Luminary.AppImage" bin="$PREFIX/bin/luminary" icon=""
    glibc_ok || refuse "this system's glibc is older than $MIN_GLIBC, which the AppImage needs"
    need_space "$PREFIX" "$NEED_APPIMAGE_MB" "the AppImage"
    mkdir -p "$dir" "$apps" "$PREFIX/bin" || die "could not create folders under $PREFIX"
    cp "$image" "$target.new" && chmod +x "$target.new" && mv -f "$target.new" "$target" \
        || die "could not copy the AppImage into $dir"
    if [ -n "$TARGET_VERSION" ]; then printf '%s\n' "$TARGET_VERSION" > "$dir/VERSION"; else rm -f "$dir/VERSION"; fi

    # Without libfuse2 an AppImage cannot mount itself; extract-and-run is the
    # same program unpacked to /tmp first, and the shell ends with it.
    local env_prefix=""
    if ! has_libfuse2; then
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
    say "Installed to $dir. To remove it, run this again with LUMINARY_UNINSTALL=1; your library is kept."
    case ":$PATH:" in *":$PREFIX/bin:"*) ;; *) say "Add $PREFIX/bin to PATH to run 'luminary' from a terminal." ;; esac
    [ -z "$(deb_package)" ] || say "The .deb build is installed too, so your menu lists Luminary twice; both open the same library."
    LAUNCH_CMD="$bin"
}

install() {
    case "$FORMAT" in
        auto) if can_use_apt; then FORMAT=deb; else FORMAT=appimage; fi ;;
        deb | appimage) ;;
        *) refuse "LUMINARY_FORMAT must be deb, appimage or auto (got '$FORMAT')" ;;
    esac
    [ "$FORMAT" = deb ] && ! can_use_apt && refuse "the .deb needs apt-get and sudo; try LUMINARY_FORMAT=appimage"

    stop_leftovers
    check_host

    local file
    if [ -n "${LUMINARY_INSTALLER:-}" ]; then
        [ -f "$LUMINARY_INSTALLER" ] || refuse "no such file: $LUMINARY_INSTALLER"
        file="$(cd "$(dirname "$LUMINARY_INSTALLER")" && pwd)/$(basename "$LUMINARY_INSTALLER")"
        TARGET_VERSION="$(file_version "$file")"
        check_version "$TARGET_VERSION"
    else
        release_json
        TARGET_VERSION="$(grep -o '"tag_name": *"[^"]*"' "$WORK/release.json" | head -1 | sed 's/.*"v\{0,1\}\([^"]*\)"$/\1/')" || TARGET_VERSION=""
        check_version "$TARGET_VERSION"
        if [ "$FORMAT" = deb ]; then
            file="$(fetch_verified _amd64.deb)"
        else
            file="$(fetch_verified _amd64.AppImage)"
        fi
    fi

    if [ "$FORMAT" = deb ]; then install_deb "$file"; else install_appimage "$file"; fi
    # Optional, so nothing in it may fail the install.
    note_user_ollama || true
    launch "$LAUNCH_CMD"
}

# Deletes a folder Luminary rebuilds on its own, and a link as a link (rm never
# follows one). Nothing a user made is ever passed here.
remove_owned() {
    [ -e "$1" ] || [ -L "$1" ] || return 0
    case "$1" in
        "$DATA_DIR/engine" | "$DATA_DIR/engine.new") ;;
        *) die "refusing to delete $1: it is not a folder Luminary rebuilds" ;;
    esac
    rm -rf -- "$1" || warn "could not remove $1"
}

# Removes the named files from $1, then $1 itself only if that left it empty.
# Whatever else is there is listed for the user, never deleted.
remove_files_then_dir() {
    local dir="$1" f
    shift
    [ -d "$dir" ] && [ ! -L "$dir" ] || return 0
    for f in "$@"; do
        [ ! -f "$dir/$f" ] || rm -f -- "$dir/$f" || warn "could not remove $dir/$f"
    done
    rmdir -- "$dir" 2>/dev/null && return 0
    KEPT+="$dir"$'\n'
}

tell_what_was_kept() {
    local dir
    if [ -n "$KEPT" ]; then
        printf '\nThese folders still hold files Luminary did not put there, so they were left alone:\n'
        while IFS= read -r dir; do
            [ -z "$dir" ] || printf '  %s\n    look:   ls -la %q\n    delete: rm -rf %q\n' "$dir" "$dir" "$dir"
        done <<< "$KEPT"
    fi
    [ -e "$DATA_DIR" ] || [ -L "$DATA_DIR" ] || return 0
    printf '\nYour library was kept at %s (%s).\n' "$DATA_DIR" "$(du -sh "$DATA_DIR" 2>/dev/null | cut -f1)"
    printf 'It holds every document, note, flashcard and review you have created, your settings\n'
    printf '(including any API keys) and the downloaded models. Reinstalling picks it up again.\n'
    if [ -L "$DATA_DIR" ]; then
        printf 'It is a link to %s; that folder is the one holding the data.\n' "$(readlink -f "$DATA_DIR")"
    fi
    printf 'To free only the models:    rm -rf %q\n' "$MODELS_DIR"
    printf 'To delete it permanently:   rm -rf %q\n' "$DATA_DIR"
}

uninstall() {
    local removed="" pkg others entry="$PREFIX/share/applications/luminary.desktop" bin="$PREFIX/bin/luminary"
    stop_leftovers
    pkg="$(deb_package)"
    if [ -n "$pkg" ]; then
        # apt also removes whatever depends on a package; remove it only when it goes alone.
        others="$(apt-get -s remove "$pkg" 2>/dev/null | awk '/^Remv / {print $2}' | grep -vxF "$pkg" | paste -sd ' ' -)" || others=""
        [ -z "$others" ] || refuse "removing $pkg would also remove: $others. Nothing was removed. If that is what you want: sudo apt remove $pkg"
        say "Removing the $pkg package with apt (asks for your password once)"
        as_root apt-get remove -y -o DPkg::Lock::Timeout=300 "$pkg" </dev/null || die "apt could not remove $pkg; try: sudo apt remove $pkg"
        removed=1
    fi
    if [ -e "$PREFIX/lib/luminary" ] || [ -e "$bin" ] || [ -e "$entry" ]; then
        say "Removing the AppImage from $PREFIX/lib/luminary"
        remove_files_then_dir "$PREFIX/lib/luminary" Luminary.AppImage Luminary.AppImage.new luminary.png VERSION
        # The launcher and menu entry are removed only when they are the ones this wrote.
        if [ -f "$bin" ] && grep -qF "$PREFIX/lib/luminary/Luminary.AppImage" "$bin"; then rm -f "$bin"; fi
        if [ -f "$entry" ] && grep -qxF "Exec=$bin" "$entry"; then rm -f "$entry"; fi
        command -v update-desktop-database >/dev/null && update-desktop-database "$PREFIX/share/applications" 2>/dev/null || true
        removed=1
    fi
    [ -n "$removed" ] || say "Luminary's app is not installed; cleaning up what an earlier install left."
    # The relocated engine is the app's own copy, rebuilt on its next launch.
    remove_owned "$DATA_DIR/engine"
    remove_owned "$DATA_DIR/engine.new"
    local f logs=(luminary.log)
    for f in "$LOG_DIR"/luminary.log.[0-9]*; do [ ! -f "$f" ] || logs+=("${f##*/}"); done
    remove_files_then_dir "$LOG_DIR" "${logs[@]}"
    say "Luminary is removed."
    tell_what_was_kept
}

# Percent-encodes $1 byte by byte, for a mailto: link.
urlencode() {
    local LC_ALL=C s="$1" out="" c i n
    for ((i = 0; i < ${#s}; i++)); do
        c="${s:i:1}"
        case "$c" in
            [a-zA-Z0-9.~_-]) out+="$c" ;;
            *) printf -v n '%d' "'$c"; printf -v c '%%%02X' $((n & 255)); out+="$c" ;;
        esac
    done
    printf '%s' "$out"
}

build_report() {
    local os="unknown" gpu nvidia
    [ -r /etc/os-release ] && os="$(. /etc/os-release && printf '%s' "${PRETTY_NAME:-unknown}")"
    gpu="$(lspci 2>/dev/null | grep -iE 'vga|3d|display' | cut -d: -f3- | paste -sd ';' -)" || true
    nvidia="$(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | paste -sd ';' -)" || true
    printf 'Luminary %s failed\n' "$ACTION"
    printf 'When: %s\n' "$(date -u '+%Y-%m-%d %H:%M:%SZ')"
    printf 'Error: %s\n' "$1"
    printf 'Requested: version %s, format %s\n' "$VERSION" "$FORMAT"
    printf 'Paths: app %s, library %s\n' "$PREFIX" "$DATA_DIR"
    printf 'System: %s, kernel %s %s\n' "$os" "$(uname -r)" "$(uname -m)"
    printf 'glibc: %s\n' "$(getconf GNU_LIBC_VERSION 2>/dev/null || echo unknown)"
    printf 'Memory: %s GB\n' "$(ram_gb)"
    printf 'Graphics: %s\n' "${gpu:-unknown}"
    printf 'NVIDIA driver: %s\n' "${nvidia:-none}"
    printf 'Free space: home %s MB, /usr %s MB, temp %s MB\n' "$(free_mb "$HOME")" "$(free_mb /usr)" "$(free_mb "${TMPDIR:-/tmp}")"
    printf 'Session: %s; libfuse2: %s\n' "${XDG_SESSION_TYPE:-none}" "$(has_libfuse2 && echo yes || echo no)"
    printf '\nSteps:\n'
    cat "$WORK/steps.log" 2>/dev/null || true
}

report() {
    local why text dir out="" answer="" user
    why="$(cat "$WORK/failure" 2>/dev/null || echo "exit without a message")"
    text="$(build_report "$why")"
    [ "${#HOME}" -le 1 ] || text="${text//"$HOME"/\~}"
    # Shorter names would redact ordinary words along with them.
    for user in "${USER:-$(id -un 2>/dev/null)}" "$(hostname 2>/dev/null)"; do
        [ "${#user}" -ge 3 ] && text="${text//"$user"/<redacted>}"
    done
    for dir in "$(xdg-user-dir DESKTOP 2>/dev/null)" "$HOME" "${TMPDIR:-/tmp}"; do
        if [ -n "$dir" ] && [ -d "$dir" ] && printf '%s\n' "$text" > "$dir/luminary-$ACTION-report.txt" 2>/dev/null; then
            out="$dir/luminary-$ACTION-report.txt"
            break
        fi
    done
    [ -n "$out" ] || return 0
    printf '\nA report of what went wrong was saved to:\n  %s\n' "$out" >&2
    if ! has_tty; then
        printf 'To get help, email it to %s.\n' "$REPORT_TO" >&2
        return 0
    fi
    printf 'It lists your Linux version, graphics card, memory, free disk space and the steps above;\n' >&2
    printf 'no documents or files of yours, and your user and computer names are removed.\n' >&2
    printf 'Email it to the Luminary developer at %s? Your mail app opens with the report filled in, and nothing is sent until you press Send. [y/N] ' "$REPORT_TO" >&2
    read -r answer </dev/tty || true
    case "$answer" in
        [yY] | [yY][eE][sS]) email_report "$out" "$why" "$text" ;;
        *) printf 'Not sent.\n' >&2 ;;
    esac
}

email_report() {
    local file="$1" subject="Luminary $ACTION failed: $2" body="$3" copied=""
    subject="${subject:0:120}"
    # Mail apps truncate or refuse long mailto: links; the full text is on the
    # clipboard and in the saved file.
    if [ "${#body}" -gt 1200 ]; then body="${body:0:1200}"$'\n[...] The full report is attached or pasted below.'; fi
    if [ -n "${WAYLAND_DISPLAY:-}" ] && command -v wl-copy >/dev/null; then
        wl-copy < "$file" 2>/dev/null && copied=1
    elif [ -n "${DISPLAY:-}" ] && command -v xclip >/dev/null; then
        xclip -selection clipboard < "$file" 2>/dev/null && copied=1
    elif [ -n "${DISPLAY:-}" ] && command -v xsel >/dev/null; then
        xsel -b < "$file" 2>/dev/null && copied=1
    fi
    if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v xdg-open >/dev/null \
        && xdg-open "mailto:$REPORT_TO?subject=$(urlencode "$subject")&body=$(urlencode "$body")" >/dev/null 2>&1; then
        printf 'Your mail app should now show the email; press Send there.\n' >&2
    else
        printf 'No mail app could be opened here.\n' >&2
    fi
    [ -z "$copied" ] || printf 'The full report is on your clipboard: with webmail, paste it into a new email to %s.\n' "$REPORT_TO" >&2
    printf 'Or attach the file: %s\n' "$file" >&2
}

main() {
    WORK="$(mktemp -d 2>/dev/null)" || {
        printf 'error: could not create a temporary folder in %s\n' "${TMPDIR:-/tmp}" >&2
        exit 1
    }
    trap 'on_error $LINENO "$BASH_COMMAND"' ERR
    trap on_exit EXIT

    [ "$(uname -s)" = Linux ] || refuse "this installer is for Linux; see the README for your system"
    [ "$(uname -m)" = x86_64 ] || refuse "Luminary is built for x86_64 only (this is $(uname -m))"
    command -v curl >/dev/null || refuse "curl is required; install it with your package manager"
    if [ "$(id -u)" = 0 ] && [ -n "${SUDO_USER:-}" ]; then
        refuse "run this as yourself, without sudo: it asks for your password when apt needs it, and Luminary must not run as root"
    fi

    if [ "$ACTION" = uninstall ]; then uninstall; else install; fi
}

main "$@"
