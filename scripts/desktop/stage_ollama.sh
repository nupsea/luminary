#!/usr/bin/env bash
# Stage the bundled inference server for the Windows and Linux installers.
# Ships the CPU and Vulkan runners only; CUDA is a verified download afterwards
# (docs/lighter-install-plan.md). Layout kept in step with OLLAMA_LIBRARY_DIR in
# src-tauri/src/stage.rs.
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
expected="$(curl -fsSL "$BASE/sha256sum.txt" \
    | awk -v a="$ASSET" '{ n = $2; sub(/^\*/, "", n); sub(/^\.\//, "", n); if (n == a) print $1 }')"
[ -n "$expected" ] || _die "$ASSET is not listed in the release's sha256sum.txt"
actual="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
if [ "$actual" != "$expected" ]; then
    rm -f "$ARCHIVE"
    _die "checksum mismatch for $ASSET (expected $expected, got $actual); removed it, re-run to download again"
fi
_info "sha256 $actual"

_step "Extracting the CPU and Vulkan runners"
rm -rf "$OL_STAGE" "$TMP"
mkdir -p "$OL_STAGE/lib" "$TMP"
# Excluded while extracting: CUDA is 1.8GB of runner disk.
if [ "$DESKTOP_OS" = linux ]; then
    command -v unzstd >/dev/null || _die "unzstd not found (install zstd)"
    tar --use-compress-program=unzstd --exclude='*cuda_v*' -xf "$ARCHIVE" -C "$TMP"
    mv "$TMP/bin/ollama" "$OL_STAGE/$EXE"
else
    uv run --no-project --python "$PY_MINOR" python - "$(native_path "$ARCHIVE")" "$(native_path "$TMP")" <<'PYEOF'
import sys, zipfile
src, dest = sys.argv[1:]
with zipfile.ZipFile(src) as z:
    z.extractall(dest, members=[n for n in z.namelist() if "/cuda_v" not in n])
PYEOF
    mv "$TMP/$EXE" "$OL_STAGE/$EXE"
fi
mv "$TMP/lib/ollama" "$LIB"
chmod +x "$OL_STAGE/$EXE"
rm -rf "$TMP"

_step "Checking what was kept"
[ -f "$OL_STAGE/$EXE" ] || _die "no $EXE in $ASSET"
[ -d "$LIB/vulkan" ] || _die "no Vulkan runner in $ASSET; with CUDA unstaged, every GPU would fall to the CPU"
if compgen -G "$LIB/cuda_v*" >/dev/null; then
    _die "CUDA was meant to be left out of the installer, found: $(cd "$LIB" && echo cuda_v*)"
fi
compgen -G "$LIB/*ggml-cpu*" >/dev/null || _die "no CPU runners in $ASSET"

relink_bundled_libs "$LIB"

# Tells engine_dir (src-tauri/src/stage.rs) whether the relocated copy is current.
printf '%s\n' "$OLLAMA_VERSION" > "$OL_STAGE/ENGINE_VERSION"

# CUDA exists only inside this archive, so the later download is the same file,
# pinned to the digest verified above.
cat > "$OL_STAGE/engine-source.json" <<JSON
{
  "version": "$OLLAMA_VERSION",
  "asset": "$ASSET",
  "url": "$BASE/$ASSET",
  "sha256": "$expected",
  "archive_bytes": $(wc -c < "$ARCHIVE" | tr -d ' '),
  "runner": "cuda_v13",
  "member_prefix": "lib/ollama/cuda_v13/"
}
JSON
uv run --no-project --python "$PY_MINOR" python -c \
    'import json,sys; json.load(open(sys.argv[1]))' "$(native_path "$OL_STAGE/engine-source.json")" \
    || _die "engine-source.json is not valid JSON"
du -sh "$OL_STAGE/$EXE" "$LIB"/*/ | sed 's|'"$OL_STAGE"'/||; s/^/    /'
_info "ollama staged: $(du -sh "$OL_STAGE" | awk '{print $1}')"
