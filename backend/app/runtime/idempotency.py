"""Writes a client may retry without doing them twice (#451).

A route opts in with `@idempotent` on a router built with `route_class=IdempotentRoute`. A
request carrying `Idempotency-Key` reserves the key for its principal before the write runs:
the same request again replays the first response, the same key on a different request is
refused, and a duplicate arriving while the first is still running is refused rather than run.
A request without the header runs as before.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

from app.database import get_session_factory
from app.exceptions import Conflict, InvalidInput
from app.repos.idempotency_repo import IdempotencyRepo
from app.types import Principal

HEADER = "idempotency-key"
MAX_KEY_CHARS = 200
# Long enough for a phone's outbox to drain after days offline.
KEY_RETENTION = timedelta(days=30)


class IdempotencyKeyReused(InvalidInput):
    """The key was already used for a different request."""


class IdempotencyKeyInFlight(Conflict):
    """The first request with this key has not finished."""


def idempotent[F: Callable[..., Any]](endpoint: F) -> F:
    endpoint._idempotent = True  # type: ignore[attr-defined]
    return endpoint


class IdempotentRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()
        if not getattr(self.endpoint, "_idempotent", False):
            return handler

        async def once(request: Request) -> Response:
            key = request.headers.get(HEADER)
            if key is None:
                return await handler(request)
            if not 0 < len(key) <= MAX_KEY_CHARS:
                raise InvalidInput(f"Idempotency-Key must be 1 to {MAX_KEY_CHARS} characters")
            principal = _principal_key(getattr(request.state, "principal", None))
            request_hash = await _request_hash(request)
            async with get_session_factory()() as session:
                held = await IdempotencyRepo(session).reserve(principal, key, request_hash)
            if held is not None:
                return _replay(held.request_hash, held.status_code, held.body, request_hash)
            try:
                response = await handler(request)
            except BaseException:
                await _release(principal, key)
                raise
            async with get_session_factory()() as session:
                repo = IdempotencyRepo(session)
                if 200 <= response.status_code < 300:
                    await repo.complete(
                        principal, key, response.status_code, bytes(response.body).decode()
                    )
                else:
                    await repo.release(principal, key)
            return response

        return once


def _principal_key(principal: Principal | None) -> str:
    if principal is not None and principal.kind == "device":
        return f"device:{principal.device_id}"
    return "local"


async def _request_hash(request: Request) -> str:
    digest = hashlib.sha256()
    for part in (request.method, request.url.path, request.url.query):
        digest.update(part.encode() + b"\0")
    digest.update(await request.body())
    return digest.hexdigest()


def _replay(held_hash: str, status: int | None, body: str | None, request_hash: str) -> Response:
    if held_hash != request_hash:
        raise IdempotencyKeyReused("this Idempotency-Key was already used for a different request")
    if status is None:
        raise IdempotencyKeyInFlight("the first request with this Idempotency-Key is still running")
    return Response(
        content=body or b"",
        status_code=status,
        media_type="application/json" if body else None,
        headers={"Idempotent-Replayed": "true"},
    )


async def _release(principal: str, key: str) -> None:
    async with get_session_factory()() as session:
        await IdempotencyRepo(session).release(principal, key)


async def prune_keys(now: datetime | None = None) -> int:
    async with get_session_factory()() as session:
        cutoff = (now or datetime.now(UTC)) - KEY_RETENTION
        return await IdempotencyRepo(session).prune(cutoff.replace(tzinfo=None))
