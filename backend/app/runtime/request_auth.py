"""Who a request acts for, and the refusal of every caller that is neither the app nor paired.

The backend binds loopback, but any page in any tab can still reach it: a form POST or a
text/plain fetch is sent without a CORS preflight and runs before the browser hides the
response. So a browser request is tokenless only from the app's own origin; any other
origin needs a paired device's bearer token (`services/devices.py`). A request with no
`Origin` is either a same-origin read or not from a browser at all (the shell, smoke,
evals); a browser marks the cross-site kind with `Sec-Fetch-Site`, and that one is refused.

Pure ASGI, like `RequestLogMiddleware`, so SSE responses are not wrapped.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.database import get_session_factory
from app.repos.device_repo import DeviceRepo
from app.services.devices import resolve_token
from app.types import LOCAL_PRINCIPAL, Principal

# Vite's dev server, and the port it falls back to when 5173 is taken (`make clean`).
DEV_APP_ORIGINS = frozenset(
    f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 5174)
)

_UNPAIRED = "This origin is not paired with Luminary. Pair it under Settings > Devices."
_NOT_ADMITTED = "This device is not paired, or its pairing was revoked."


def needs_token(
    origin: str | None, sec_fetch_site: str | None, own_origin: str, app_origins: frozenset[str]
) -> bool:
    if origin is not None:
        return origin != own_origin and origin not in app_origins
    return sec_fetch_site == "cross-site"


class RequestAuthMiddleware:
    def __init__(
        self, app: ASGIApp, *, api_prefix: str, app_origins: frozenset[str], pair_path: str
    ) -> None:
        self.app = app
        self.api_prefix = api_prefix
        self.app_origins = app_origins
        # Reachable unpaired, or nothing could ever pair.
        self.pair_path = pair_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not self._guards(scope["path"]):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        authorization = headers.get("authorization")
        if authorization is not None:
            principal = await self._device(authorization)
            if principal is None:
                await self._refuse(scope, receive, send, _NOT_ADMITTED)
                return
        elif scope["path"] == self.pair_path:
            principal = None
        elif needs_token(
            headers.get("origin"),
            headers.get("sec-fetch-site"),
            f"{scope.get('scheme', 'http')}://{headers.get('host', '')}",
            self.app_origins,
        ):
            await self._refuse(scope, receive, send, _UNPAIRED)
            return
        else:
            principal = LOCAL_PRINCIPAL

        scope.setdefault("state", {})["principal"] = principal
        await self.app(scope, receive, send)

    def _guards(self, path: str) -> bool:
        # In public mode only the API is guarded: the SPA's files are public, and the
        # root probes are reads the shell makes before the SPA exists.
        return not self.api_prefix or path.startswith(self.api_prefix + "/")

    @staticmethod
    async def _device(authorization: str) -> Principal | None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None
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
