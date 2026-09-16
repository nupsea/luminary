#!/usr/bin/env bash
# Stage the bundled inference server for the Windows and Linux installers.
#
# Ollama's archive for these platforms is ~1.4GB because it carries two CUDA
# generations. This keeps the CPU runners, Vulkan and CUDA 13, and leaves out
# CUDA 12 (1.15GB of the Windows archive). A GPU that CUDA 13 cannot serve --
# an older card, or a driver below its floor -- runs through Vulkan instead,
# which vendor drivers ship on Windows and Mesa or the vendor packages provide
# on Linux. AMD is Vulkan-only here: ROCm is a separate archive.
#
# Layout: `ollama/ollama[.exe]` beside `ollama/lib/ollama/`, a place Ollama
# searches relative to its own executable on both platforms (ml/path.go). Kept
# in step with OLLAMA_LIBRARY_DIR in src-tauri/src/stage.rs.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

case "$DESKTOP_OS" in
    linux) ASSET="ollama-linux-amd64.tar.zst" EXE="ollama" ;;
    windows) ASSET="ollama-windows-amd64.zip" EXE="ollama.exe" ;;
    macos) _die "macOS stages Ollama with scripts/macos/stage_ollama.sh" ;;
    *) _die "no desktop bundle for $(uname -s)" ;;
esac

BASE="https://github.com/ollama/ollama/releases/download/$OLLAMA_VERSION"
ARCHIVE="$BUILD_DIR/ollama-$OLLAMA_VERSION-$ASSET"
OL_STAGE="$STAGE/ollama"
LIB="$OL_STAGE/lib/ollama"
TMP="$BUILD_DIR/ollama-extract"
mkdir -p "$BUILD_DIR"

if [ ! -f "$ARCHIVE" ]; then
    _step "Downloading Ollama $OLLAMA_VERSION ($ASSET)"
    curl -fL --progress-bar "$BASE/$ASSET" -o "$ARCHIVE.part"
    mv "$ARCHIVE.part" "$ARCHIVE"
fi

_step "Checking the archive against the release checksums"
# A truncated download extracts partially and fails at the first generation, on
# a user's machine rather than here.
expected="$(curl -fsSL "$BASE/sha256sum.txt" \
    | awk -v a="$ASSET" '{ n = $2; sub(/^\*/, "", n); sub(/^\.\//, "", n); if (n == a) print $1 }')"
[ -n "$expected" ] || _die "$ASSET is not listed in the release's sha256sum.txt"
actual="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
if [ "$actual" != "$expected" ]; then
    rm -f "$ARCHIVE"
    _die "checksum mismatch for $ASSET (expected $expected, got $actual); removed it, re-run to download again"
fi
_info "sha256 $actual"

_step "Extracting the CPU, Vulkan and CUDA 13 runners"
rm -rf "$OL_STAGE" "$TMP"
mkdir -p "$OL_STAGE/lib" "$TMP"
# CUDA 12 is excluded while extracting rather than deleted afterwards: it is over
# a gigabyte of disk on a runner that also holds two copies of the stage.
if [ "$DESKTOP_OS" = linux ]; then
    command -v unzstd >/dev/null || _die "unzstd not found (install zstd)"
    tar --use-compress-program=unzstd --exclude='*cuda_v12*' -xf "$ARCHIVE" -C "$TMP"
    mv "$TMP/bin/ollama" "$OL_STAGE/$EXE"
else
    uv run --no-project --python "$PY_MINOR" python - "$(native_path "$ARCHIVE")" "$(native_path "$TMP")" <<'PYEOF'
import sys, zipfile
src, dest = sys.argv[1:]
with zipfile.ZipFile(src) as z:
    z.extractall(dest, members=[n for n in z.namelist() if "/cuda_v12/" not in n])
PYEOF
    mv "$TMP/$EXE" "$OL_STAGE/$EXE"
fi
mv "$TMP/lib/ollama" "$LIB"
chmod +x "$OL_STAGE/$EXE"
rm -rf "$TMP"

_step "Checking what was kept"
[ -f "$OL_STAGE/$EXE" ] || _die "no $EXE in $ASSET"
[ -d "$LIB/cuda_v13" ] || _die "no CUDA 13 runner in $ASSET"
[ -d "$LIB/vulkan" ] || _die "no Vulkan runner in $ASSET; a GPU CUDA 13 cannot serve would fall to the CPU"
[ ! -e "$LIB/cuda_v12" ] || _die "CUDA 12 was meant to be left out"
compgen -G "$LIB/*ggml-cpu*" >/dev/null || _die "no CPU runners in $ASSET"
du -sh "$OL_STAGE/$EXE" "$LIB"/*/ | sed 's|'"$OL_STAGE"'/||; s/^/    /'
_info "ollama staged: $(du -sh "$OL_STAGE" | awk '{print $1}')"
