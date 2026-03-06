#!/usr/bin/env bash
# PreToolUse hook — blocks pip install to enforce the uv invariant.
# Reads JSON from stdin, writes JSON to stdout, exits 2 to block.

INPUT=$(cat)

COMMAND=$(printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('command', ''))
except Exception:
    print('')
" 2>/dev/null || echo "")

if printf '%s' "$COMMAND" | grep -qE '(^|\s)(pip3?)\s+install'; then
    echo "[Luminary Invariant #1] BLOCKED: Never use pip install." >&2
    echo "  Use: cd backend && uv add <package>" >&2
    printf '%s' "$INPUT"
    exit 2
fi

printf '%s' "$INPUT"
