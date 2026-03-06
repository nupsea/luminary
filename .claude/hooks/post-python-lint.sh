#!/usr/bin/env bash
# PostToolUse hook — runs ruff check after any Python file in backend/ is edited.
# Async and non-blocking; writes warnings to stderr only.

INPUT=$(cat)

FILE=$(printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('file_path', ''))
except Exception:
    print('')
" 2>/dev/null || echo "")

if [[ "$FILE" == *.py ]] && [[ "$FILE" == */backend/* ]]; then
    REPO_ROOT=$(git -C "$(dirname "$FILE")" rev-parse --show-toplevel 2>/dev/null || echo "")
    if [[ -n "$REPO_ROOT" ]]; then
        RESULT=$(cd "$REPO_ROOT/backend" && uv run ruff check "$FILE" 2>&1) || true
        if [[ -n "$RESULT" ]]; then
            echo "[Luminary Lint] ruff issues in $(basename "$FILE"):" >&2
            echo "$RESULT" >&2
        fi
    fi
fi

printf '%s' "$INPUT"
