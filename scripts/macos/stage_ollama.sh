#!/usr/bin/env bash
# Stage the bundled inference server.
#
# We ship Ollama rather than raw llama-server so the backend's LiteLLM
# `ollama/` provider, model registry, pull-with-progress, keep_alive and vision
# handling all keep working unchanged. We run our OWN instance on a private
# port with its own OLLAMA_MODELS, so a user's existing Ollama.app is never
# touched and there is no supervisor contention on 11434.
#
# The official ollama-darwin.tgz is the only viable source. A Homebrew-derived
# tree cannot be bundled: it contains a mlx_metal_v3/libmlxc.dylib symlink into
# /opt/homebrew that would dangle on every user's machine.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

OL_STAGE="$STAGE/ollama"
TGZ="$BUILD_DIR/ollama-darwin-$OLLAMA_VERSION.tgz"
URL="https://github.com/ollama/ollama/releases/download/$OLLAMA_VERSION/ollama-darwin.tgz"

mkdir -p "$BUILD_DIR"

if [ ! -f "$TGZ" ]; then
    _step "Downloading Ollama $OLLAMA_VERSION"
    curl -fL --progress-bar "$URL" -o "$TGZ.part"
    mv "$TGZ.part" "$TGZ"
fi
_info "$(du -h "$TGZ" | awk '{print $1}') $TGZ"

_step "Extracting into the stage"
rm -rf "$OL_STAGE"
mkdir -p "$OL_STAGE"
tar -xzf "$TGZ" -C "$OL_STAGE"

# The darwin tarball is flat: ollama, llama-server and the runner libs all sit
# side by side. (A Homebrew install nests them under lib/ollama -- do not use
# that layout as a reference.) OLLAMA_LIBRARY_PATH therefore points at this dir.
for b in ollama llama-server; do
    [ -f "$OL_STAGE/$b" ] || _die "$b missing from $URL"
    chmod +x "$OL_STAGE/$b"
done

_step "Thinning universal binaries to arm64"
# `ollama` itself ships universal (68MB -> 31MB thinned).
while IFS= read -r -d '' f; do
    archs="$(lipo -archs "$f" 2>/dev/null || true)"
    if echo "$archs" | grep -q arm64 && echo "$archs" | grep -q x86_64; then
        lipo -thin arm64 "$f" -output "$f.thin" && mv -f "$f.thin" "$f" && chmod +x "$f"
    fi
done < <(macho_files "$OL_STAGE")

_step "Dropping the Intel runner"
# Measured, not assumed: `ollama` and `llama-server` are arm64 and link only
# system frameworks -- llama-server statically embeds arm64 ggml + Metal. Every
# libggml*/libllama*/libmtmd* dylib in the tarball is x86_64-only, i.e. the
# Intel runner's, and is dead weight in an Apple-Silicon-only app.
removed=0
while IFS= read -r f; do
    archs="$(lipo -archs "$f" 2>/dev/null || true)"
    case "$archs" in
        *x86_64*) echo "$archs" | grep -q arm64 || { rm -f "$f"; removed=$((removed + 1)); } ;;
    esac
done < <(find "$OL_STAGE" -type f)
find "$OL_STAGE" -type l ! -exec test -e {} \; -delete   # symlinks to what we just removed
_info "dropped $removed Intel-only binaries"

# MLX is Apple-Silicon inference for MLX-format models only; GGUF (everything we
# ship -- see the model manifest) runs through llama-server. Verified by
# verify_ollama.sh: pull + generate succeed with these gone. 323MB of 404MB.
rm -rf "$OL_STAGE/mlx_metal_v3" "$OL_STAGE/mlx_metal_v4"

# Only used by `ollama create`, which we never call.
rm -f "$OL_STAGE/llama-quantize"

find "$OL_STAGE" -type d -empty -delete

_info "ollama staged: $(du -sh "$OL_STAGE" | awk '{print $1}')"
