#!/usr/bin/env bash
# Stage the application payload (backend source, SPA, manifest, licenses).
#
# $STAGE becomes Contents/Resources in the .app. The layout mirrors the repo
# tree because backend/app resolves surface-manifest.json, frontend/dist,
# alembic.ini and pyproject.toml via Path(__file__).resolve().parents[2] --
# from <stage>/backend/app/config.py that is <stage>. Same contract as the
# release tarball in .github/workflows/release.yml.
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
        VITE_LUMINARY_MODE=public VITE_API_BASE=/api npm run build
    )
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

# Ollama is MIT and statically vendors MIT llama.cpp. Both notices must ship in
# binary distributions; this is a license obligation, not a nicety.
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
# The code executor was deleted from the repo -- it ran arbitrary code as the
# desktop user with full filesystem and network access. This guard fails the
# build if it is ever reintroduced, rather than shipping it to an end user.
! [ -e "$STAGE/backend/app/routers/code_executor.py" ] || _die "code_executor leaked into the payload"
! grep -rq "/Users/$(whoami)" "$STAGE/backend/app" || _die "personal path in payload"

_info "payload staged ($(du -sh "$STAGE/backend" "$STAGE/frontend" | awk '{print $1}' | paste -sd+ -))"
