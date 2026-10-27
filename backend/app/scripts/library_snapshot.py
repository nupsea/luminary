"""Take a library's snapshot, or restore one as a new library (#390).

Usage::

    uv run python -m app.scripts.library_snapshot snapshot ~/luminary.tar.gz
    uv run python -m app.scripts.library_snapshot restore ~/luminary.tar.gz --as odyssey

A snapshot is safe to take while the app runs. A restored library migrates to this
version's schema the first time it is opened.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from app.library import use_library
from app.services.library_snapshot import restore_snapshot, take_snapshot


async def main(args: argparse.Namespace) -> int:
    path = Path(args.archive).expanduser()
    if args.command == "snapshot":
        with use_library(args.library):
            manifest = await take_snapshot(path)
    else:
        manifest = await restore_snapshot(path, args.as_library)
    summary = {k: v for k, v in asdict(manifest).items() if k != "files"}
    print(json.dumps({**summary, "files": len(manifest.files)}, indent=2))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot", help="write the library's snapshot to ARCHIVE")
    snap.add_argument("archive")
    snap.add_argument("--library", default="default", help="the library to snapshot")
    restore = sub.add_parser("restore", help="restore ARCHIVE as a new library")
    restore.add_argument("archive")
    restore.add_argument("--as", dest="as_library", required=True, help="the new library's id")
    sys.exit(asyncio.run(main(ap.parse_args())))
