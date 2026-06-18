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
import logging
import sys

from app.database import get_engine, get_session_factory
from app.db_init import create_all_tables
from app.services.concept_extraction_service import regenerate

logger = logging.getLogger(__name__)


async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO)
    await create_all_tables(get_engine())
    async with get_session_factory()() as session:
        stats = await regenerate(session, target_themes=args.themes)
    print(stats)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate the Concept layer (themes).")
    parser.add_argument("--themes", type=int, default=25, help="target top-level themes")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
