#!/usr/bin/env bash
# Stage the application payload (backend source, SPA, manifest, licenses).
# Mirrors the repo tree: backend/app resolves its resources via parents[2].
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

BUILD_SPA="${BUILD_SPA:-1}"

_step "Staging application payload into $STAGE"
rm -rf "$STAGE/backend" "$STAGE/frontend" "$STAGE/licenses"
mkdir -p "$STAGE/backend" "$STAGE/frontend" "$STAGE/licenses"

if [ "$BUILD_SPA" = "1" ]; then
    _step "Building SPA (public mode)"
    (
        cd "$REPO_ROOT/frontend"
        [ -d node_modules ] || npm ci
        # Git Bash otherwise rewrites "/api" to "C:/Program Files/Git/api" for node.exe.
        MSYS2_ENV_CONV_EXCL=VITE_API_BASE \
            VITE_LUMINARY_MODE=public VITE_API_BASE=/api npm run build
    )
    if grep -rqE '"[A-Za-z]:/[^"]*/api"' "$REPO_ROOT/frontend/dist/assets"; then
        _die "SPA baked a drive-letter API base; VITE_API_BASE was path-converted"
    fi
fi
[ -f "$REPO_ROOT/frontend/dist/index.html" ] || _die "frontend/dist/index.html missing; run with BUILD_SPA=1"

cp "$REPO_ROOT/surface-manifest.json" "$STAGE/"
cp -R "$REPO_ROOT/frontend/dist" "$STAGE/frontend/dist"
cp -R "$REPO_ROOT/backend/app" "$STAGE/backend/app"
cp -R "$REPO_ROOT/backend/alembic" "$STAGE/backend/alembic"
cp "$REPO_ROOT/backend/alembic.ini" "$REPO_ROOT/backend/pyproject.toml" "$STAGE/backend/"

find "$STAGE/backend" "$STAGE/frontend" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGE/backend" "$STAGE/frontend" \( -name '*.pyc' -o -name '*.db' -o -name '.DS_Store' \) -delete

_step "Staging third-party notices"
cp "$REPO_ROOT/LICENSE" "$STAGE/licenses/LUMINARY-LICENSE"

# License obligation: Ollama and its vendored llama.cpp (both MIT).
curl -fsSL "https://raw.githubusercontent.com/ollama/ollama/$OLLAMA_VERSION/LICENSE" \
    -o "$STAGE/licenses/OLLAMA-LICENSE"
curl -fsSL "https://raw.githubusercontent.com/ggml-org/llama.cpp/master/LICENSE" \
    -o "$STAGE/licenses/LLAMA.CPP-LICENSE"

_step "Verifying payload layout"
for f in surface-manifest.json frontend/dist/index.html backend/app/main.py \
         backend/alembic.ini backend/pyproject.toml \
         licenses/OLLAMA-LICENSE licenses/LLAMA.CPP-LICENSE; do
    [ -e "$STAGE/$f" ] || _die "missing from stage: $f"
done
[ -d "$STAGE/backend/alembic/versions" ] || _die "missing alembic/versions"
# The code executor ran arbitrary code as the user; fail if it ever comes back.
! [ -e "$STAGE/backend/app/routers/code_executor.py" ] || _die "code_executor leaked into the payload"
! grep -rqE "/(Users|home)/$(whoami)/" "$STAGE/backend/app" || _die "personal path in payload"

_info "payload staged ($(du -sh "$STAGE/backend" "$STAGE/frontend" | awk '{print $1}' | paste -sd+ -))"
