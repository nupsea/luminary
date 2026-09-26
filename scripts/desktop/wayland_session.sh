#!/usr/bin/env bash
# Run a command inside a headless Wayland session with XWayland, the way a GNOME or
# KDE Wayland desktop hosts the app. xvfb on the runner cannot show an I-62 blank
# window: its Mesa is the one the AppImage was built against.
#
#   scripts/desktop/wayland_session.sh <command> [args...]
#
# Needs sway, Xwayland and dbus-launch. In a container sway needs CAP_SYS_NICE.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[ "$#" -gt 0 ] || _die "usage: wayland_session.sh <command> [args...]"
mkdir -p "$BUILD_DIR"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-$(mktemp -d)}"
chmod 700 "$XDG_RUNTIME_DIR"
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1
conf="$(mktemp)"
printf 'xwayland enable\noutput HEADLESS-1 resolution 1440x900\n' > "$conf"
eval "$(dbus-launch --sh-syntax)"

sway -c "$conf" > "$BUILD_DIR/sway.log" 2>&1 &
sway_pid=$!
trap 'kill "$sway_pid" 2>/dev/null || true' EXIT

export WAYLAND_DISPLAY=""
for _ in $(seq 1 50); do
    sock="$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -name 'wayland-*' -type s | head -1)"
    [ -n "$sock" ] && { WAYLAND_DISPLAY="$(basename "$sock")"; break; }
    sleep 0.2
done
[ -n "$WAYLAND_DISPLAY" ] || { cat "$BUILD_DIR/sway.log"; _die "sway did not start"; }

# XWayland starts lazily, but its socket exists as soon as sway does.
DISPLAY=""
for _ in $(seq 1 50); do
    x="$(find /tmp/.X11-unix -maxdepth 1 -name 'X*' 2>/dev/null | head -1)"
    [ -n "$x" ] && { DISPLAY=":${x##*/X}"; break; }
    sleep 0.2
done
[ -n "$DISPLAY" ] || { cat "$BUILD_DIR/sway.log"; _die "sway started without XWayland"; }
export DISPLAY
_info "Wayland session: WAYLAND_DISPLAY=$WAYLAND_DISPLAY DISPLAY=$DISPLAY"

"$@"
