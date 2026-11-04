"""Run a connector for one request: `python -m luminary_source_sdk.serve package.module:Class`.

Luminary starts this per call. A connector's own `print` would corrupt the protocol, so the
protocol keeps the real stdout and everything else the process prints goes to stderr, which
the core logs.
"""

from __future__ import annotations

import importlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO

from luminary_source_sdk import protocol
from luminary_source_sdk.bundle import BundleError, BundleWriter
from luminary_source_sdk.connector import Connector, ConnectorError

_MAX_REQUEST_BYTES = 1024 * 1024


def _load(entry: str) -> Connector:
    module_name, _, attr = entry.partition(":")
    cls = getattr(importlib.import_module(module_name), attr)
    if not (isinstance(cls, type) and issubclass(cls, Connector)):
        raise TypeError(f"{entry} is not a Connector subclass")
    return cls()


def _dispatch(connector: Connector, req: dict[str, Any], emit) -> dict[str, Any]:
    op, inp, creds = req["op"], req.get("input") or {}, req.get("credentials") or {}
    if op == "describe":
        return connector.describe().to_json()
    if op == "check":
        return connector.check(creds).to_json()
    if op == "preview":
        return connector.preview(inp, creds).to_json()
    dest = Path(req["dest"])
    connector.fetch(inp, creds, BundleWriter(dest), lambda f, s="": emit(protocol.progress(f, s)))
    if not (dest / "manifest.json").is_file():
        raise ConnectorError("internal", "fetch returned without writing manifest.json")
    return {"bundle": str(dest)}


def handle(raw: str, entry: str, out: TextIO) -> int:
    """Answer one request line on `out`; the process exit code."""

    def emit(event: dict[str, Any]) -> None:
        out.write(json.dumps(event, ensure_ascii=False) + "\n")
        out.flush()

    try:
        req = json.loads(raw)
        if req.get("protocol") != protocol.PROTOCOL_VERSION:
            raise ConnectorError("internal", f"protocol {req.get('protocol')!r} is not supported")
        if req.get("op") not in protocol.OPS:
            raise ConnectorError("internal", f"unknown op {req.get('op')!r}")
        emit(protocol.result(_dispatch(_load(entry), req, emit)))
        return 0
    except ConnectorError as exc:
        emit(protocol.error(exc.code, exc.message))
    except BundleError as exc:
        emit(protocol.error("internal", f"bad bundle: {exc}"))
    except Exception as exc:  # noqa: BLE001 - every failure must reach the core as an event
        emit(protocol.error("internal", f"{type(exc).__name__}: {exc}"))
    return 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m luminary_source_sdk.serve package.module:Class", file=sys.stderr)
        return 2
    out = io.TextIOWrapper(os.fdopen(os.dup(sys.stdout.fileno()), "wb"), encoding="utf-8")
    sys.stdout = sys.stderr
    raw = sys.stdin.buffer.read(_MAX_REQUEST_BYTES + 1)
    if len(raw) > _MAX_REQUEST_BYTES:
        out.write(json.dumps(protocol.error("internal", "request too large")) + "\n")
        out.flush()
        return 1
    return handle(raw.decode("utf-8"), args[0], out)


if __name__ == "__main__":
    sys.exit(main())
