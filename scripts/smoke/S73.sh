#!/usr/bin/env bash
# Smoke test for S73: Flashcard smart question generation and flip animation fix
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/../../backend" && pwd)"

echo "S73 smoke: verifying FLASHCARD_SYSTEM prompt quality guidance"
cd "$BACKEND_DIR"
uv run python - <<'EOF'
from app.services.flashcard import FLASHCARD_SYSTEM

assert "comprehension" in FLASHCARD_SYSTEM, "FLASHCARD_SYSTEM missing 'comprehension'"
assert "application" in FLASHCARD_SYSTEM, "FLASHCARD_SYSTEM missing 'application'"
assert "AVOID" in FLASHCARD_SYSTEM, "FLASHCARD_SYSTEM missing 'AVOID'"
assert "hypothetical" in FLASHCARD_SYSTEM, "FLASHCARD_SYSTEM missing 'hypothetical'"

print("PASS: FLASHCARD_SYSTEM contains taxonomy guidance and AVOID block")
EOF
