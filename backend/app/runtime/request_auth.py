"""Who a request acts for, and the refusal of every caller that is neither the app nor paired.

The backend binds loopback, but any page in any tab can still reach it: a form POST or a
text/plain fetch is sent without a CORS preflight and runs before the browser hides the
response. So a browser request is tokenless only from the app's own origin; any other
origin needs a paired device's bearer token (`services/devices.py`). A request with no
`Origin` is either a same-origin read or not from a browser at all (the shell, smoke,
evals); a browser marks the cross-site kind with `Sec-Fetch-Site`, and that one is refused.

Those headers are only evidence on loopback. A server that answers beyond it
(`LUMINARY_ALLOWED_HOSTS`, #511) admits a non-loopback client by token alone, since a direct
client writes whatever `Origin` and `Host` it likes.

The request then runs in its principal's library (#388): a device's is the one it paired into,
the app's is the active library (`services/libraries.py`). Devices are looked up in the
default library's database, the registry, whatever library they belong to.

Pure ASGI, like `RequestLogMiddleware`, so SSE responses are not wrapped.
"""

from __future__ import annotations

import dataclasses
import ipaddress
from collections.abc import Callable

from fastapi import Request
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.database import get_session_factory
from app.exceptions import Forbidden
from app.library import use_library
from app.repos.device_repo import DeviceRepo
from app.runtime.library_work import serve_library
from app.services.devices import resolve_token
from app.services.libraries import active_library
from app.types import DEFAULT_LIBRARY, LOCAL_PRINCIPAL, Principal

# Vite's dev server, and the port it falls back to when 5173 is taken (`make clean`).
DEV_APP_ORIGINS = frozenset(
    f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 5174)
)

_UNPAIRED = "This origin is not paired with Luminary. Pair it under Settings > Devices."
_NOT_ADMITTED = "This device is not paired, or its pairing was revoked."
_REMOTE = "Requests from another machine need a paired device's token."


def is_loopback(client: tuple[str, int] | None) -> bool:
    if client is None:
        return False
    try:
        return ipaddress.ip_address(client[0]).is_loopback
    except ValueError:
        return False


def require_local(refusal: str) -> Callable[[Request], None]:
    """A route dependency that refuses every caller but the app itself."""

    def check(request: Request) -> None:
        principal = getattr(request.state, "principal", None)
        if principal is None or principal.kind != "local":
            raise Forbidden(refusal)

    return check


def needs_token(
    origin: str | None, sec_fetch_site: str | None, own_origin: str, app_origins: frozenset[str]
) -> bool:
    if origin is not None:
        return origin != own_origin and origin not in app_origins
    return sec_fetch_site == "cross-site"


class RequestAuthMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        api_prefix: str,
        app_origins: frozenset[str],
        pair_path: str,
        remote_needs_token: bool = False,
    ) -> None:
        self.app = app
        self.remote_needs_token = remote_needs_token
        self.api_prefix = api_prefix
        self.app_origins = app_origins
        # Reachable unpaired, or nothing could ever pair.
        self.pair_path = pair_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not self._guards(scope["path"]):
            await self.app(scope, receive, send)
            return

        principal, refusal = await self._principal(scope)
        if refusal is not None:
            await self._refuse(scope, receive, send, refusal)
            return

        if principal is not None and principal.kind == "local":
            principal = dataclasses.replace(principal, library=active_library())
        library = principal.library if principal is not None else DEFAULT_LIBRARY
        if library != DEFAULT_LIBRARY:  # startup serves the default
            await serve_library(library)
        scope.setdefault("state", {})["principal"] = principal
        with use_library(library):
            await self.app(scope, receive, send)

    async def _principal(self, scope: Scope) -> tuple[Principal | None, str | None]:
        """Who the request acts for, or why it is refused. No principal only for pairing."""
        headers = Headers(scope=scope)
        authorization = headers.get("authorization")
        if authorization is not None:
            principal = await self._device(authorization)
            return (principal, None) if principal is not None else (None, _NOT_ADMITTED)
        if scope["path"] == self.pair_path:
            return None, None
        if self.remote_needs_token and not is_loopback(scope.get("client")):
            return None, _REMOTE
        own_origin = f"{scope.get('scheme', 'http')}://{headers.get('host', '')}"
        if needs_token(
            headers.get("origin"), headers.get("sec-fetch-site"), own_origin, self.app_origins
        ):
            return None, _UNPAIRED
        return LOCAL_PRINCIPAL, None

    def _guards(self, path: str) -> bool:
        # In public mode only the API is guarded: the SPA's files are public, and the
        # root probes are reads the shell makes before the SPA exists.
        return not self.api_prefix or path.startswith(self.api_prefix + "/")

    @staticmethod
    async def _device(authorization: str) -> Principal | None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None
        with use_library(DEFAULT_LIBRARY):
            async with get_session_factory()() as session:
                return await resolve_token(DeviceRepo(session), token.strip())

    @staticmethod
    async def _refuse(scope: Scope, receive: Receive, send: Send, detail: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        response = JSONResponse(
            {"detail": detail}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
        )
        await response(scope, receive, send)
