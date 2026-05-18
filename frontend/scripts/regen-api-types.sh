#!/usr/bin/env bash
# Regenerate frontend/src/types/api.ts from the FastAPI OpenAPI schema.
#
# Pipeline:
#   1. boot the backend module enough to call app.openapi() and dump the
#      schema to a tmp file (no uvicorn -- module-load only)
#   2. feed it to openapi-typescript, write the result to
#      frontend/src/types/api.ts
#
# Run from repo root or anywhere -- the script resolves its own paths.
#
# When to run:
#   - after adding/removing a Pydantic schema field
#   - after changing a route signature or response_model
#   - never as part of the dev loop -- run it once when the contract
#     changes and commit the regenerated file
set -euo pipefail

# Resolve paths relative to this script so the command works from any cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"
OUT_FILE="$FRONTEND_DIR/src/types/api.ts"

TMP_SCHEMA="$(mktemp -t openapi.XXXXXX.json)"
trap 'rm -f "$TMP_SCHEMA"' EXIT

echo "==> Dumping OpenAPI schema from $BACKEND_DIR"
( cd "$BACKEND_DIR" && uv run python -m tools.dump_openapi ) > "$TMP_SCHEMA"

echo "==> Generating $OUT_FILE"
( cd "$FRONTEND_DIR" && npx openapi-typescript "$TMP_SCHEMA" -o "$OUT_FILE" )

echo "==> Done. $(wc -l <"$OUT_FILE") lines written to src/types/api.ts"
