"""Re-embed a library's vectors from its database, with the app stopped (#390).

Usage::

    uv run python -m app.scripts.reembed
    uv run python -m app.scripts.reembed --library odyssey

A run killed midway resumes when started again. The vectors it replaces are kept as
`vectors.previous` in the library's folder; remove that folder once the app answers as before.
"""

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict

from app.db_init import open_library
from app.library import use_library
from app.services.library_snapshot import DATABASE
from app.services.reembed import reembed
from app.storage import library_root


async def main(args: argparse.Namespace) -> int:
    if not (library_root(library=args.library) / DATABASE).exists():
        print(f"no library {args.library!r} at {library_root(library=args.library)}")
        return 1
    # Brings the database to this version's schema, as the app does when it opens it.
    await open_library(args.library)
    with use_library(args.library):
        report = await reembed()
    print(json.dumps(asdict(report), indent=2))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--library", default="default", help="the library to re-embed")
    sys.exit(asyncio.run(main(ap.parse_args())))
