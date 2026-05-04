"""CLI: validate every JSONL file in evals/golden/ against the retrieval schema.

Usage::

    uv run python -m evals.lib.audit
"""

import sys

from evals.lib.loader import GOLDEN_DIR, GoldenValidationError, load_golden
from evals.lib.schemas import RetrievalGoldenEntry


def main() -> int:
    if not GOLDEN_DIR.exists():
        print(f"FAIL: golden directory not found: {GOLDEN_DIR}", file=sys.stderr)
        return 1
    files = sorted(GOLDEN_DIR.glob("*.jsonl"))
    if not files:
        print(f"FAIL: no .jsonl files found in {GOLDEN_DIR}", file=sys.stderr)
        return 1

    failures = 0
    for path in files:
        dataset = path.stem
        try:
            rows = load_golden(dataset, RetrievalGoldenEntry)
        except (GoldenValidationError, FileNotFoundError) as exc:
            print(f"FAIL {dataset}: {exc}")
            failures += 1
            continue
        print(f"PASS {dataset}: {len(rows)} entries")
    return 1 if failures > 0 else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
