"""The connector protocol: one request on stdin, then events on stdout, one JSON object a line.

Luminary starts a connector process per call and writes one request line:

    {"protocol": 1, "op": "describe" | "preview" | "fetch",
     "input": {...}, "credentials": {...}, "dest": "/dir/the/core/named"}

The connector answers with event lines and exits:

    {"event": "progress", "fraction": 0.4, "stage": "downloading"}
    {"event": "log", "level": "info", "message": "..."}
    {"event": "result", "data": {...}}                       # last line on success
    {"event": "error", "code": "auth", "message": "..."}      # last line on failure

Credentials arrive only in the request, never in argv or the environment.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

PROTOCOL_VERSION = 1
OPS = ("describe", "preview", "fetch")
ERROR_CODES = ("input", "auth", "source", "internal")
LOG_LEVELS = ("debug", "info", "warning", "error")

Op = Literal["describe", "preview", "fetch"]


@dataclass(frozen=True)
class Field:
    """An input or credential the core asks the user for."""

    name: str
    label: str
    secret: bool = False
    required: bool = True
    help: str = ""


@dataclass(frozen=True)
class Terms:
    """What the source's own terms page says about this use, quoted, and where."""

    statement: str
    url: str


@dataclass(frozen=True)
class Description:
    """What `describe` returns: everything the core shows before the connector runs."""

    name: str
    version: str
    licence: str
    terms: Terms
    # Links this connector takes, by prefix: `https://www.example.com/watch`.
    url_prefixes: list[str] = field(default_factory=list)
    inputs: list[Field] = field(default_factory=list)
    credentials: list[Field] = field(default_factory=list)
    preview: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def request(
    op: Op,
    *,
    input: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
    dest: str | None = None,
) -> str:
    return json.dumps(
        {
            "protocol": PROTOCOL_VERSION,
            "op": op,
            "input": input or {},
            "credentials": credentials or {},
            "dest": dest,
        }
    )


def progress(fraction: float, stage: str = "") -> dict[str, Any]:
    return {"event": "progress", "fraction": min(1.0, max(0.0, float(fraction))), "stage": stage}


def log(level: str, message: str) -> dict[str, Any]:
    return {"event": "log", "level": level if level in LOG_LEVELS else "info", "message": message}


def result(data: dict[str, Any]) -> dict[str, Any]:
    return {"event": "result", "data": data}


def error(code: str, message: str) -> dict[str, Any]:
    return {"event": "error", "code": code if code in ERROR_CODES else "internal", "message": message}
