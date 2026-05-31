#!/usr/bin/env bash
# Guards against module-level labs/dev imports leaking into public routers:
# the backend must import under the public install profile (no labs/dev groups).
# Runs in an isolated env so the working .venv is left intact.
set -euo pipefail

cd "$(dirname "$0")/../backend"

# Use a fixed path (not TMPDIR-dependent) and always recreate to avoid
# stale environments that produce "unknown location" FastAPI import errors.
PUBLIC_ENV="/tmp/luminary-public-env"
export UV_PROJECT_ENVIRONMENT="$PUBLIC_ENV"

echo "Recreating public profile env in $PUBLIC_ENV ..."
rm -rf "$PUBLIC_ENV"
uv sync --no-default-groups --quiet

echo "Importing app.main under LUMINARY_SURFACE_TIER=public ..."
LUMINARY_SURFACE_TIER=public PHOENIX_ENABLED=false \
  uv run --no-default-groups --no-sync python -c "import app.main; print('public-profile import OK')"
