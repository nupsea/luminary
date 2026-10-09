"""A StreamingResponse that stops at the generator's next yield when the client goes away (I-65).

Starlette's cancels mid-await, which strands a database connection caught mid-query.
"""

import anyio
from starlette.responses import StreamingResponse as _StarletteStreamingResponse
from starlette.types import Receive, Scope, Send


class StreamingResponse(_StarletteStreamingResponse):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        gone = anyio.Event()

        async def watch() -> None:
            await self.listen_for_disconnect(receive)
            gone.set()

        try:
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(watch)
                await self._stream_until_gone(send, gone)
                task_group.cancel_scope.cancel()
        finally:
            # Closes at the yield it stopped on, so its `async with` blocks exit normally.
            aclose = getattr(self.body_iterator, "aclose", None)
            if aclose is not None:
                await aclose()

        if self.background is not None:
            await self.background()

    async def _stream_until_gone(self, send: Send, gone: anyio.Event) -> None:
        await send(
            {"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers}
        )
        async for chunk in self.body_iterator:
            if gone.is_set():
                return
            body = chunk if isinstance(chunk, bytes | memoryview) else chunk.encode(self.charset)
            await send({"type": "http.response.body", "body": body, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})
