"""The kind is optional on /documents/ingest: omitting it is the request to classify.

The type field was mandatory (S63) until the upload dialog was found to be
defaulting every non-media file to "book", which -- because a supplied type skips
classification outright -- meant auto-detection never ran for any upload.
"""

import io

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.anyio
async def test_ingest_without_a_kind_classifies(test_db, monkeypatch):
    """Omitting the kind is accepted, and passes no type so classify_node runs.

    None specifically, not a placeholder: classify_node treats any type it is
    given as the caller's decision and skips every heuristic.
    """
    called: list[str | None] = []

    async def _noop() -> None:
        return None

    # Recorded at call time, not inside the coroutine body: the job never runs
    # here, so a mock that appends when awaited would record nothing and the
    # assertion below would pass on an empty list.
    def _mock_run_ingestion(document_id, file_path, format, content_type=None, **_):
        called.append(content_type)
        return _noop()

    import app.routers.documents as documents_module

    monkeypatch.setattr(documents_module, "run_ingestion", _mock_run_ingestion)
    monkeypatch.setattr(
        documents_module.get_ingestion_jobs(), "launch", lambda doc_id, coro: coro.close()
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/documents/ingest",
            files={"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")},
        )
    assert resp.status_code == 200, resp.text
    assert called == [None]


@pytest.mark.anyio
async def test_an_unknown_kind_returns_422(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/documents/ingest",
            files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
            data={"kind": "unknown_kind"},
        )
    assert resp.status_code == 422
