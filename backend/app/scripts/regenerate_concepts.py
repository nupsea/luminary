"""Regenerate the Concept layer from the entity graph (the real concept model).

Wipes the existing concepts and rebuilds a small set of higher-level themes (with
sub-concepts) via the multi-layer pipeline in concept_extraction_service -- NOT the old
1:1 entity promotion. See docs/concepts.md.

Run OFFLINE (server stopped) so it can hold the Kuzu lock and use the LLM without
starving the live event loop. Self-migrates the schema. Idempotent (wipe + rebuild).

    make concepts
    # or:
    cd backend && DATA_DIR=<repo>/.luminary uv run python -m app.scripts.regenerate_concepts
    #   --themes N   (target number of top-level themes; default 25)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from app.config import get_settings
from app.database import get_engine
from app.db_init import create_all_tables

logger = logging.getLogger(__name__)


def _dump_diagnostics(diagnostics: dict) -> None:
    """Pretty-print the per-node diagnostics and persist last_run.json for inspection."""
    print("\n===== concept pipeline diagnostics (dry run) =====")
    print(json.dumps(diagnostics, indent=2, default=str))
    try:
        out_dir = Path(get_settings().DATA_DIR).expanduser() / "concepts"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "last_run.json").write_text(json.dumps(diagnostics, indent=2, default=str))
        print(f"\n(report written to {out_dir / 'last_run.json'})")
    except Exception as exc:
        logger.warning("could not write last_run.json: %s", exc)


async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO)
    await create_all_tables(get_engine())

    # The node pipeline (select -> embed -> build_hierarchy -> label -> persist) is the
    # one path. dry_run runs every node except persist and dumps the report; a real run
    # persists the named galaxy/constellation/concept hierarchy.
    from app.workflows.concept_pipeline import run_pipeline  # noqa: PLC0415

    state = await run_pipeline(dry_run=args.dry_run)
    _dump_diagnostics(state.get("diagnostics", {}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate the Concept layer (themes).")
    parser.add_argument("--themes", type=int, default=25, help="target top-level themes")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="run the node pipeline without persisting; dump diagnostics for inspection",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
