#!/usr/bin/env bash
# Turn a screen recording into a README-ready GIF.
#
#   scripts/make_gif.sh raw.mov offline
#
# Writes assets/images/<name>.gif, then prints the Markdown to paste.
# Two-pass palette: a global palette banks colours the UI never uses and
# renders text mushy, so the palette is generated from this clip's own frames.
set -euo pipefail

SRC="${1:-}"
NAME="${2:-demo}"
FPS="${FPS:-12}"          # 12 is enough for UI motion and roughly halves 24fps
WIDTH="${WIDTH:-900}"     # README column width; wider is unreadable once scaled
START="${START:-}"        # e.g. START=2.5 to trim the lead-in
DURATION="${DURATION:-}"  # e.g. DURATION=12
MAX_MB="${MAX_MB:-5}"

usage() {
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}
[ -n "$SRC" ] || usage
[ -f "$SRC" ] || { echo "no such file: $SRC" >&2; exit 1; }
command -v ffmpeg >/dev/null || {
  echo "ffmpeg not found. Install it with: brew install ffmpeg" >&2; exit 1; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/assets/images/${NAME}.gif"
PAL="$(mktemp -t luminary-pal).png"
mkdir -p "$(dirname "$OUT")"

TRIM=()
[ -n "$START" ]    && TRIM+=(-ss "$START")
[ -n "$DURATION" ] && TRIM+=(-t "$DURATION")

FILTER="fps=${FPS},scale=${WIDTH}:-1:flags=lanczos"

echo "==> palette (${FPS}fps, ${WIDTH}px)"
ffmpeg -hide_banner -loglevel error -y "${TRIM[@]}" -i "$SRC" \
  -vf "${FILTER},palettegen=stats_mode=diff" "$PAL"

echo "==> encode"
ffmpeg -hide_banner -loglevel error -y "${TRIM[@]}" -i "$SRC" -i "$PAL" \
  -lavfi "${FILTER}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3" "$OUT"
rm -f "$PAL"

BYTES=$(wc -c < "$OUT" | tr -d ' ')
MB=$(echo "scale=1; $BYTES/1048576" | bc)
echo "==> $OUT  (${MB} MB)"

if [ "$BYTES" -gt $((MAX_MB * 1048576)) ]; then
  cat >&2 <<EOF

WARNING: over ${MAX_MB} MB. GitHub will not paint this before the reader
scrolls past it. Try, in this order:

  DURATION=10 $0 $SRC $NAME     # cut a beat -- the cheapest win
  FPS=10      $0 $SRC $NAME
  WIDTH=800   $0 $SRC $NAME

Do not drop the beat where the answer streams in: a GIF that jumps to a
finished answer reads as staged.
EOF
fi

cat <<EOF

Paste into README.md:

<p align="center">
  <img src="assets/images/${NAME}.gif" alt="DESCRIBE WHAT HAPPENS" width="${WIDTH}">
</p>

Replace the alt text. It is what screen readers announce and what shows if
the image fails to load, so describe the action, not the file.
EOF
