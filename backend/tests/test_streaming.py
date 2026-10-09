"""A client disconnect must not cancel a stream mid-query (app/streaming.py)."""

import asyncio
import gc
import logging
import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.streaming import StreamingResponse

# Long enough that the disconnect lands mid-query: ~0.3s here, against a 20ms disconnect.
SLOW_QUERY = (
    "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 3000000) "
    "SELECT count(*) FROM c"
)
DISCONNECT_AFTER_S = 0.02

SCOPE = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}}


async def _serve(response, sent: list[dict]) -> None:
    """Drive a response as uvicorn does, with the client leaving after DISCONNECT_AFTER_S."""

    async def receive():
        await asyncio.sleep(DISCONNECT_AFTER_S)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await response(SCOPE, receive, send)


async def test_disconnect_lets_the_awaited_work_finish_and_stops_at_the_yield():
    events: list[str] = []

    async def gen():
        try:
            yield "data: first\n\n"
            await asyncio.sleep(DISCONNECT_AFTER_S * 5)
            events.append("work finished")
            yield "data: after the client left\n\n"
            events.append("ran past the yield")
        finally:
            events.append("closed")

    sent: list[dict] = []
    await _serve(StreamingResponse(gen(), media_type="text/event-stream"), sent)

    assert events == ["work finished", "closed"]
    bodies = [m.get("body") for m in sent if m["type"] == "http.response.body"]
    assert bodies == [b"data: first\n\n"]


async def test_disconnect_mid_query_returns_the_connection(tmp_path, caplog):
    """Starlette's own class fails this: the pool logs "Exception terminating connection"
    and the stranded connection then holds up engine disposal."""
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'stream.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def gen():
        async with factory() as session:
            count = (await session.execute(text(SLOW_QUERY))).scalar()
        yield f"data: {count}\n\n"

    with caplog.at_level(logging.ERROR, logger="sqlalchemy.pool"):
        await _serve(StreamingResponse(gen(), media_type="text/event-stream"), [])
        gc.collect()

    assert [r.getMessage() for r in caplog.records if r.name.startswith("sqlalchemy.pool")] == []
    assert engine.pool.checkedout() == 0
    await engine.dispose()


def test_every_streaming_route_uses_the_disconnect_safe_response():
    app_dir = Path(__file__).parent.parent / "app"
    pattern = re.compile(r"from (fastapi|starlette)\.responses import [^\n]*\bStreamingResponse\b")
    offenders = [
        str(p.relative_to(app_dir))
        for p in app_dir.rglob("*.py")
        if p.name != "streaming.py" and pattern.search(p.read_text())
    ]
    assert offenders == []
