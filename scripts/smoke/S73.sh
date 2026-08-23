#!/usr/bin/env bash
# Smoke test for S73: the flashcard system prompt states shape, never a taxonomy.
#
# This script used to assert that FLASHCARD_SYSTEM contained "comprehension" and
# "application" -- it required the taxonomy vocabulary that I-28 exists to keep
# out. A level label is not a specification: the model pattern-matches the word
# to the register it has seen it in, which is how "Bloom taxonomy level 5
# (Evaluate)" produced exam papers. The prompt now names what a card asks the
# reader to do -- fact / explain / use / relate / limit / build -- and the
# taxonomy stays in the codebase's own mapping.
#
# I-28 records that `tests/test_suggestions.py` guards the suggestions prompt and
# that `services/flashcard_prompts.py` is "the same defect unguarded". This is
# that guard.
#
# Verifies:
#   1. the depth vocabulary is present and is the observable kind
#   2. the AVOID block survives
#   3. no taxonomy term has crept back in
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/../../backend" && pwd)"

cd "$BACKEND_DIR"
uv run python - <<'EOF'
from app.services.flashcard import FLASHCARD_SYSTEM

# The observable shape words the prompt asks for.
for word in ("fact", "explain", "use", "relate", "limit", "build"):
    assert word in FLASHCARD_SYSTEM, f"FLASHCARD_SYSTEM missing depth word {word!r}"

assert "AVOID" in FLASHCARD_SYSTEM, "FLASHCARD_SYSTEM missing the AVOID block"
assert "SOURCE_EXCERPT" in FLASHCARD_SYSTEM, "the prompt no longer demands a quote"

# I-28: the taxonomy is the codebase's, never the model's.
lowered = FLASHCARD_SYSTEM.lower()
for term in ("bloom", "taxonomy", "comprehension", "application", "synthesis"):
    assert term not in lowered, (
        f"taxonomy term {term!r} is back in FLASHCARD_SYSTEM -- I-28: a prompt "
        f"states the shape of what it wants, never the name of a taxonomy"
    )

print("PASS: FLASHCARD_SYSTEM states shape, names no taxonomy, keeps AVOID")
EOF
