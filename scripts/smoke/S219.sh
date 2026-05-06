#!/usr/bin/env bash
# Smoke test for S219: generated golden dataset backend.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

HELP="$(cd "$ROOT/evals" && uv run --no-sync python run_eval.py --help)"
grep -q -- "--dataset-id" <<<"$HELP"

uv run --project "$ROOT/backend" --no-sync pytest \
  "$ROOT/backend/tests/test_dataset_generator_service.py" \
  "$ROOT/backend/tests/test_evals_router.py"

uv run --project "$ROOT/backend" --no-sync ruff check \
  "$ROOT/backend/app/services/dataset_generator_service.py" \
  "$ROOT/backend/app/routers/evals.py" \
  "$ROOT/backend/tests/test_dataset_generator_service.py" \
  "$ROOT/backend/tests/test_evals_router.py" \
  "$ROOT/evals/run_eval.py"

echo "PASS: S219 -- generated golden dataset API, quality filter, and CLI dataset-id wiring are green"
