#!/usr/bin/env bash
# Smoke test for S69: Markdown rendering — QA system prompt contains Markdown instruction
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/../../backend" && pwd)"

echo "S69 smoke: asserting QA_SYSTEM_PROMPT contains Markdown instruction"
cd "$BACKEND_DIR"
uv run python - <<'EOF'
from app.services.qa import QA_SYSTEM_PROMPT
assert "Markdown" in QA_SYSTEM_PROMPT, f"QA_SYSTEM_PROMPT missing Markdown instruction: {QA_SYSTEM_PROMPT}"
from app.services.summarizer import _build_system_prompt, LIBRARY_SYSTEM_PROMPTS
for mode in ("executive", "detailed"):
    p = _build_system_prompt(mode)
    assert "Markdown" in p, f"_build_system_prompt({mode!r}) missing Markdown instruction"
    lp = LIBRARY_SYSTEM_PROMPTS[mode]
    assert "Markdown" in lp, f"LIBRARY_SYSTEM_PROMPTS[{mode!r}] missing Markdown instruction"
print("PASS: all prompts contain Markdown instruction")
EOF
