#!/usr/bin/env bash
# Smoke test for S52: End-to-end integration test structure — verify test file exists and
# is correctly marked @pytest.mark.slow (excluded from default make test).
# Requires backend dev dependencies installed (uv sync).

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/../../backend" && pwd)"

# 1. Verify test file exists
TEST_FILE="$BACKEND_DIR/tests/test_e2e_book.py"
if [ ! -f "$TEST_FILE" ]; then
  echo "FAIL: $TEST_FILE not found"
  exit 1
fi

# 2. Verify file is marked slow (not collected by default make test)
if ! grep -q "pytest.mark.slow" "$TEST_FILE"; then
  echo "FAIL: test_e2e_book.py missing pytest.mark.slow — would run in default CI"
  exit 1
fi

# 3. Verify conftest_books plugin reference
if ! grep -q "conftest_books" "$TEST_FILE"; then
  echo "FAIL: test_e2e_book.py missing pytest_plugins = [\"tests.conftest_books\"]"
  exit 1
fi

# 4. Verify test collection (dry-run, no execution)
cd "$BACKEND_DIR"
COLLECTED=$(uv run pytest tests/test_e2e_book.py --collect-only -q -m slow 2>&1 | grep "test session starts" -A 50 | grep -c "test_" || true)
if [ "$COLLECTED" -lt 5 ]; then
  echo "FAIL: expected >= 5 test items collected, got $COLLECTED"
  exit 1
fi

echo "PASS: S52 test file exists, marked slow, collects >= 5 tests"
