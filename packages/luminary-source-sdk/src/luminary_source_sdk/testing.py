"""Run a connector in-process the way Luminary runs it, for a connector's own tests."""

from __future__ import annotations

import contextlib
import http.server
import io
import json
import threading
from collections.abc import Iterator
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


@contextlib.contextmanager
def serve_pages(pages: dict[str, str | bytes | tuple[int, str]]) -> Iterator[str]:
    """A local web server for a connector's tests, answering each path in *pages* (a body, or
    `(status, body)`) and 404 to anything else. Yields its base URL, without a trailing slash."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 -- the stdlib's name
            found = pages.get(self.path)
            status, body = found if isinstance(found, tuple) else (200, found)
            if found is None:
                status, body = 404, "not found"
            data = body.encode() if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: Any) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
