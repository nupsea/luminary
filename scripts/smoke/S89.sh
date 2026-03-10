#!/usr/bin/env bash
# Smoke test for S89: Notes markdown rendering -- @tailwindcss/typography and highlight.js
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FRONTEND="$REPO_ROOT/frontend"

echo "S89 smoke: building frontend..."
cd "$FRONTEND" && npm run build --cache /tmp/npm-cache-user
echo "S89 smoke: build passed"

echo "S89 smoke: verifying @tailwindcss/typography in tailwind.config.cjs..."
grep -q '@tailwindcss/typography' "$FRONTEND/tailwind.config.cjs"
echo "S89 smoke: tailwind.config.cjs check passed"

echo "S89 smoke: verifying highlight.js import in src/index.css..."
grep -q "highlight.js/styles/github.css" "$FRONTEND/src/index.css"
echo "S89 smoke: index.css check passed"

echo "S89: all smoke checks passed"
