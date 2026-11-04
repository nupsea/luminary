"""The connector protocol: one request on stdin, then events on stdout, one JSON object a line.

Luminary starts a connector process per call and writes one request line:

    {"protocol": 1, "op": "describe" | "check" | "preview" | "fetch",
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
OPS = ("describe", "check", "preview", "fetch")
ERROR_CODES = ("input", "auth", "source", "internal")
LOG_LEVELS = ("debug", "info", "warning", "error")
MEDIA = ("text", "audio", "youtube")
TOOLS = ("ffmpeg",)

Op = Literal["describe", "check", "preview", "fetch"]


@dataclass(frozen=True)
class Field:
    """An input or credential the core asks the user for."""

    name: str
    label: str
    secret: bool = False
    required: bool = True
    help: str = ""
    # A pasted block (a cookie export) rather than one line.
    multiline: bool = False


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    detail: str = ""


@dataclass(frozen=True)
class Choice:
    """A pick the user makes before a fetch; its values reach `fetch` as `input[field]`, a
    list when `multiple`, else one value."""

    field: str
    label: str
    options: list[Option]
    multiple: bool = False
    default: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Preview:
    """What `preview` returns: what the link is, and the choices before fetching it."""

    title: str
    detail: str = ""
    choices: list[Choice] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Account:
    """What `check` returns for a set of credentials."""

    valid: bool
    account: str | None = None
    message: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


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
    # What the user calls the source ("YouTube"), for messages; the name when empty.
    label: str = ""
    # Links this connector takes, by prefix: `https://www.example.com/watch`.
    url_prefixes: list[str] = field(default_factory=list)
    inputs: list[Field] = field(default_factory=list)
    credentials: list[Field] = field(default_factory=list)
    preview: bool = False
    # The bundle kinds it writes ("text", "audio", "youtube"); the core checks it can
    # ingest them before a fetch starts.
    media: list[str] = field(default_factory=lambda: ["text"])
    # Host tools it runs, from `TOOLS`. The core finds each and passes its path in the
    # fetch input as `input["tools"][name]`, or refuses the link before fetching.
    tools: list[str] = field(default_factory=list)

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
    code = code if code in ERROR_CODES else "internal"
    return {"event": "error", "code": code, "message": message}
