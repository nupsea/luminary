#!/usr/bin/env bash
# Smoke test for S202: CI gate errors and browser console errors sweep
# Verifies all three CI gates pass cleanly.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=true

echo "=== S202 Smoke Test ==="

# 1. ruff check
echo "--- Gate 1: ruff check ---"
if (cd "$REPO_ROOT/backend" && uv run ruff check . 2>&1); then
  echo "PASS: ruff check exits 0"
else
  echo "FAIL: ruff check had errors"
  PASS=false
fi

# 2. pytest (non-slow)
echo "--- Gate 2: pytest ---"
if (cd "$REPO_ROOT/backend" && uv run pytest -x -q --ignore=tests/test_corpus_qa.py 2>&1 | tail -5); then
  echo "PASS: pytest exits 0"
else
  echo "FAIL: pytest had failures"
  PASS=false
fi

# 3. tsc --noEmit
echo "--- Gate 3: tsc --noEmit ---"
if (cd "$REPO_ROOT/frontend" && npx tsc --noEmit 2>&1); then
  echo "PASS: tsc --noEmit exits 0"
else
  echo "FAIL: tsc --noEmit had errors"
  PASS=false
fi

if [ "$PASS" = true ]; then
  echo "=== S202 Smoke: ALL PASSED ==="
  exit 0
else
  echo "=== S202 Smoke: SOME FAILED ==="
  exit 1
fi
