"""Request status and latency for the requests a failure report needs (#110).

The bundled app runs uvicorn with `--no-access-log`, because polling would bury
everything else. A route chunk that fails to load in the packaged app therefore
left no trace of its request's status or timing. This logs only:

- every request outside the API when the backend also serves the SPA, since
  those are the route chunks and the index, and there are few of them;
- any response of 400 or above, and any request that raised or never finished;
- any response that started late: the I-2 stall this exists to catch shows up
  as a late first byte, not as a long SSE stream.

A pure ASGI middleware rather than `BaseHTTPMiddleware`, which wraps streaming
responses and would sit between every SSE answer and its client.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# A loopback file or JSON response starts within milliseconds; an event loop
# blocked by an unwrapped Kuzu or embedding call (I-2) holds it for seconds.
SLOW_FIRST_BYTE_MS = 1000.0


class RequestLogMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        api_prefix: str,
        serves_spa: bool,
        quiet_paths: frozenset[str] = frozenset(),
    ) -> None:
        self.app = app
        self.api_prefix = api_prefix
        self.serves_spa = serves_spa
        # Health endpoints: mounted outside the prefix too, and polled.
        self.quiet_paths = quiet_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        state: dict[str, Any] = {"status": None, "first_byte_ms": None, "complete": False}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                state["first_byte_ms"] = (time.perf_counter() - started) * 1000
            elif message["type"] == "http.response.body" and not message.get("more_body"):
                state["complete"] = True
            await send(message)

        error: BaseException | None = None
        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException as exc:
            error = exc
            raise
        finally:
            self._record(scope, state, (time.perf_counter() - started) * 1000, error)

    def _record(
        self, scope: Scope, state: dict[str, Any], total_ms: float, error: BaseException | None
    ) -> None:
        path: str = scope.get("path", "")
        status = state["status"]
        first_byte_ms = state["first_byte_ms"]
        outside_api = (
            self.serves_spa
            and not path.startswith(self.api_prefix + "/")
            and path not in self.quiet_paths
        )
        failed = error is not None or not state["complete"] or (status or 0) >= 400
        slow = first_byte_ms is None or first_byte_ms >= SLOW_FIRST_BYTE_MS
        if not (outside_api or failed or slow):
            return
        logger.log(
            logging.WARNING if failed or slow else logging.INFO,
            "request %s %s -> %s in %.0fms (first byte %s)",
            scope.get("method", ""),
            path,
            status if status is not None else "no response",
            total_ms,
            f"{first_byte_ms:.0f}ms" if first_byte_ms is not None else "never",
            extra={
                "path": path,
                "status": status,
                "first_byte_ms": round(first_byte_ms, 1) if first_byte_ms is not None else None,
                "total_ms": round(total_ms, 1),
                "complete": state["complete"],
                "error": type(error).__name__ if error is not None else None,
            },
        )
