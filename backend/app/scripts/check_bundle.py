"""Import a source bundle the way the library does, and print what Luminary reads from it.

The connector conformance kit runs this (`luminary_source_sdk.conformance --luminary`); it
needs no database and stores nothing. Prints one JSON line: `{"title", "media", "sections":
[{"heading", "text"}]}`, or `{"error"}` with exit status 1 when the importer refuses it.

Usage::

    cd backend && uv run python -m app.scripts.check_bundle /path/to/bundle
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from app.exceptions import LuminaryError
from app.services.connectors import MEDIA
from app.services.source_bundle import BUNDLE_SUFFIX, parse_bundle, store_bundle


def read(bundle: Path) -> dict:
    with tempfile.TemporaryDirectory() as scratch:
        stored = Path(scratch) / f"check{BUNDLE_SUFFIX}"
        manifest = store_bundle(bundle, stored, media=frozenset(MEDIA))
        out: dict = {"title": manifest.title, "media": manifest.media.kind, "sections": []}
        if manifest.media.kind == "text":
            out["sections"] = [
                {"heading": s.heading, "text": s.text} for s in parse_bundle(stored).sections
            ]
        return out


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    try:
        print(json.dumps(read(Path(argv[0])), ensure_ascii=False))
    except LuminaryError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
