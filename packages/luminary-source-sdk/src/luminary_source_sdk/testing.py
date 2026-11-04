"""Run a connector in-process the way Luminary runs it, for a connector's own tests."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from luminary_source_sdk import protocol
from luminary_source_sdk.serve import handle


def run(
    entry: str,
    op: protocol.Op,
    *,
    input: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
    dest: Path | None = None,
) -> list[dict[str, Any]]:
    """Every event the connector emits for one request; the last is `result` or `error`."""
    out = io.StringIO()
    raw = protocol.request(
        op, input=input, credentials=credentials, dest=str(dest) if dest else None
    )
    handle(raw, entry, out)
    return [json.loads(line) for line in out.getvalue().splitlines()]
