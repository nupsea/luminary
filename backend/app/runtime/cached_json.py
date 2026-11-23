"""A JSON response a client can revalidate and receive compressed (#452).

The ETag is the hash of the exact body, so it changes whenever any byte would; a client that
sends it back gets 304 and no body. Compression is applied here, per response, rather than by a
middleware that would also hold back the answer streams (SSE) and recompress ranged audio and PDF.
"""

from __future__ import annotations

import gzip
import hashlib

from fastapi import Request, Response
from pydantic import BaseModel

# Below this, gzip's header and the CPU cost outweigh what it saves.
_COMPRESS_FROM_BYTES = 1024


def cached_json(request: Request, payload: BaseModel) -> Response:
    body = payload.model_dump_json().encode()
    etag = f'"{hashlib.sha256(body).hexdigest()[:32]}"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache", "Vary": "Accept-Encoding"}
    if etag in _tags(request.headers.get("if-none-match", "")):
        return Response(status_code=304, headers=headers)
    if len(body) >= _COMPRESS_FROM_BYTES and "gzip" in request.headers.get("accept-encoding", ""):
        body = gzip.compress(body, compresslevel=6)
        headers["Content-Encoding"] = "gzip"
    return Response(content=body, media_type="application/json", headers=headers)


def _tags(header: str) -> set[str]:
    # A weak validator from an intermediary still names the same bytes for a GET.
    return {t.strip().removeprefix("W/") for t in header.split(",") if t.strip()}
