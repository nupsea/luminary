"""Write the source bundle's JSON Schema, the published form of `BundleManifest`.

Run from backend/:
    uv run python -m tools.dump_bundle_schema
"""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas.source_bundle import BundleManifest

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "luminary-source-sdk"
    / "schema"
    / "source-bundle.schema.json"
)


def render() -> str:
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
    schema |= BundleManifest.model_json_schema()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(render(), encoding="utf-8")
    print(SCHEMA_PATH)
