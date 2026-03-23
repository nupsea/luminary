#!/usr/bin/env bash
# S105 smoke test: pack_context respects token budget and ProgressDashboard lazy-loads
# Tests:
#   1. Backend unit tests for context_packer pass (token budget + accuracy)
#   2. Frontend tsc --noEmit passes (lazy import type safety)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "S105 [1/2]: Running context_packer unit tests..."
cd "${REPO_ROOT}/backend"
uv run pytest tests/test_context_packer.py -q --tb=short 2>&1
echo "PASS: context_packer tests"

echo "S105 [2/2]: TypeScript type check..."
cd "${REPO_ROOT}/frontend"
npx tsc --noEmit 2>&1
echo "PASS: tsc --noEmit"

echo "S105: ALL CHECKS PASSED"
