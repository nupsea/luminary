#!/usr/bin/env bash
# PreToolUse hook — warns when installing or importing OpenAI/Anthropic SDKs directly.
# Enforces invariant #5: all LLM calls must go through LiteLLM.
# Exits 2 to block pip/uv add of direct provider packages.

INPUT=$(cat)

COMMAND=$(printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('command', ''))
except Exception:
    print('')
" 2>/dev/null || echo "")

if printf '%s' "$COMMAND" | grep -qE '(uv add|pip install|pip3 install)\s.*(openai|anthropic)([^-]|$)'; then
    echo "[Luminary Invariant #5] BLOCKED: Never install OpenAI or Anthropic SDKs directly." >&2
    echo "  All LLM calls must go through LiteLLM. Use: litellm.completion(...)" >&2
    printf '%s' "$INPUT"
    exit 2
fi

printf '%s' "$INPUT"
