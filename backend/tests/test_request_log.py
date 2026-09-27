"""#110: a route chunk that fails to load must leave its status and latency behind."""

import asyncio
import logging

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Route

from app import request_log
from app.request_log import RequestLogMiddleware


async def _ok(request):
    return JSONResponse({"ok": True})


async def _asset(request):
    return PlainTextResponse("body{}")


async def _boom(request):
    return JSONResponse({"detail": "no"}, status_code=500)


async def _slow(request):
    await asyncio.sleep(0.05)
    return JSONResponse({"ok": True})


async def _stream(request):
    async def gen():
        yield "data: first\n\n"
        await asyncio.sleep(0.05)
        yield "data: last\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


def _app() -> RequestLogMiddleware:
    inner = Starlette(
        routes=[
            Route("/api/ok", _ok),
            Route("/api/boom", _boom),
            Route("/api/slow", _slow),
            Route("/api/stream", _stream),
            Route("/assets/chunk.css", _asset),
            Route("/healthz", _ok),
        ]
    )
    return RequestLogMiddleware(
        inner, api_prefix="/api", serves_spa=True, quiet_paths=frozenset({"/healthz"})
    )


async def _get(path: str) -> None:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        await client.get(path)


def _logged(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.request_log"]


@pytest.fixture(autouse=True)
def _fast_threshold(monkeypatch):
    # 50ms handlers against a 20ms bar, so "slow" is decided by the test's own sleep.
    monkeypatch.setattr(request_log, "SLOW_FIRST_BYTE_MS", 20.0)


@pytest.mark.asyncio
async def test_a_route_chunk_is_logged_with_status_and_timing(caplog):
    caplog.set_level(logging.INFO)
    await _get("/assets/chunk.css")

    (record,) = _logged(caplog)
    assert record.status == 200
    assert record.path == "/assets/chunk.css"
    assert record.first_byte_ms is not None and record.total_ms >= record.first_byte_ms
    assert record.complete is True


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/ok", "/healthz", "/api/stream"])
async def test_a_healthy_api_call_a_poll_and_a_long_stream_stay_quiet(caplog, path):
    """A stream that starts at once is healthy however long it runs."""
    caplog.set_level(logging.INFO)
    await _get(path)
    assert _logged(caplog) == []


@pytest.mark.asyncio
async def test_an_error_response_is_logged_as_a_warning(caplog):
    caplog.set_level(logging.INFO)
    await _get("/api/boom")

    (record,) = _logged(caplog)
    assert record.levelno == logging.WARNING
    assert record.status == 500


@pytest.mark.asyncio
async def test_a_late_first_byte_is_logged_as_a_warning(caplog):
    caplog.set_level(logging.INFO)
    await _get("/api/slow")

    (record,) = _logged(caplog)
    assert record.levelno == logging.WARNING
    assert record.first_byte_ms >= 20.0


@pytest.mark.asyncio
async def test_a_request_that_raises_is_logged_with_no_response(caplog):
    async def raises(scope, receive, send):
        raise RuntimeError("handler crashed")

    caplog.set_level(logging.INFO)
    app = RequestLogMiddleware(raises, api_prefix="/api", serves_spa=True)
    with pytest.raises(RuntimeError):
        await app({"type": "http", "method": "GET", "path": "/api/x"}, None, None)

    (record,) = _logged(caplog)
    assert record.status is None
    assert record.error == "RuntimeError"
    assert "no response" in record.getMessage()


def test_the_app_is_wired_with_the_request_log():
    from app.main import app

    assert any(m.cls is RequestLogMiddleware for m in app.user_middleware)
