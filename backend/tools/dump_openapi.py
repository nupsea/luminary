"""Dump the FastAPI OpenAPI schema to stdout as JSON.

Used by `frontend/scripts/regen-api-types.sh` to feed
`openapi-typescript`, which writes typed API models to
`frontend/src/types/api.ts`.

Run:
    uv run python -m tools.dump_openapi > /tmp/openapi.json

Notes
-----
- Loads `app.main:app` so all routers + Pydantic models are registered.
  This is a one-time module import; the FastAPI lifespan never runs.
- Output is the raw OpenAPI 3.x dict that FastAPI builds from route
  metadata + Pydantic v2 schemas. We don't filter or post-process --
  the consumer (openapi-typescript) handles the rest.
"""

from __future__ import annotations

import contextlib
import json
import sys


def main() -> int:
    # Importing the app is not quiet: PyMuPDF's deprecated `fitz` alias prints a
    # notice on stdout, and a single stray line ahead of the JSON silently
    # corrupts the 20k-line file this feeds. Anything a dependency writes while
    # the app loads goes to stderr, where it is still visible.
    with contextlib.redirect_stdout(sys.stderr):
        from app.main import app  # noqa: PLC0415

        schema = app.openapi()

    json.dump(schema, sys.stdout, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
