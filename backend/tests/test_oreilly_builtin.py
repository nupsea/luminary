"""The built-in O'Reilly import, reached through /documents/ingest-url until #467 removes it.
Its settings, preview and chapter selection belong to the O'Reilly connector now (#436)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import DocumentModel
from app.services.ingestion_jobs import get_ingestion_jobs
from app.services.oreilly_service import delete_oreilly_cookies
from tests.oreilly_book import BOOK_ID, BOOK_URL, FixtureBookClient


@pytest.fixture(autouse=True)
def clean_cookies():
    delete_oreilly_cookies()
    yield
    delete_oreilly_cookies()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _signed_in(module: str, book: FixtureBookClient):
    """`module`'s OreillyClient() returns the fixture book, as a stored session would."""
    return patch(f"{module}.OreillyClient", lambda *_a, **_k: book)


async def _ingest(body: dict, book: FixtureBookClient, monkeypatch) -> tuple[dict, AsyncMock]:
    """POST /documents/ingest-url and wait for its job; the ingestion graph itself is not run."""
    ingested = AsyncMock()
    monkeypatch.setattr("app.workflows.oreilly_ingestion.run_ingestion", ingested)
    with _signed_in("app.workflows.oreilly_ingestion", book):
        async with _client() as client:
            resp = await client.post("/documents/ingest-url", json=body)
            assert resp.status_code == 200, resp.text
            await get_ingestion_jobs().get(resp.json()["document_id"])
    return resp.json(), ingested


async def _document(factory, doc_id: str) -> DocumentModel:
    async with factory() as session:
        return await session.get(DocumentModel, doc_id)


@pytest.mark.asyncio
async def test_oreilly_ingest_stores_the_book_and_hands_it_to_ingestion(test_db, monkeypatch):
    _, factory, tmp_path = test_db
    book = FixtureBookClient()
    result, ingested = await _ingest({"url": BOOK_URL}, book, monkeypatch)

    doc_id = result["document_id"]
    assert result == {"document_id": doc_id, "status": "processing", "title": "Fixture Systems"}
    doc = await _document(factory, doc_id)
    stored = tmp_path / "raw" / f"{doc_id}.epub"
    assert (doc.title, doc.format, doc.source_url, doc.file_path, doc.stage) == (
        "Fixture Systems",
        "epub",
        BOOK_URL,
        str(stored),
        "parsing",
    )
    assert doc.tags == ["oreilly", "tech-book"]
    assert stored.exists()
    ingested.assert_awaited_once_with(doc_id, str(stored), "epub")
    assert sum(url.endswith(".html") for url in book.fetched) == 3


@pytest.mark.asyncio
async def test_a_chapter_url_ingests_that_chapter_as_its_own_document(test_db, monkeypatch):
    _, factory, _ = test_db
    book = FixtureBookClient()
    url = f"{BOOK_URL}ch02.html#leaders"
    result, _ = await _ingest({"url": url}, book, monkeypatch)

    assert [u.rsplit("/", 1)[-1] for u in book.fetched if u.endswith(".html")] == ["ch02.html"]
    doc = await _document(factory, result["document_id"])
    assert (doc.title, doc.tags, doc.source_url) == (
        "Fixture Systems — 2. Replication",
        ["oreilly", "tech-chapter"],
        url,
    )


@pytest.mark.asyncio
async def test_a_failed_download_marks_the_document_and_ingests_nothing(test_db, monkeypatch):
    _, factory, tmp_path = test_db
    failing = FixtureBookClient(failing=frozenset({"ch01.html"}))
    result, ingested = await _ingest({"url": BOOK_URL}, failing, monkeypatch)

    doc = await _document(factory, result["document_id"])
    assert doc.stage == "error"
    assert doc.error_message == (
        "O'Reilly download failed: Could not download 1 of 3 chapters "
        f"of O'Reilly book {BOOK_ID}: 1. Storage"
    )
    ingested.assert_not_called()
    assert list((tmp_path / "raw").iterdir()) == []


@pytest.mark.asyncio
async def test_a_download_failing_mid_write_removes_the_partial_file(test_db, monkeypatch):
    _, factory, tmp_path = test_db

    def _partial_write(name, _book, *_a, **_k):
        Path(name).write_bytes(b"PK\x03\x04partial")
        raise OSError("No space left on device")

    monkeypatch.setattr("app.services.oreilly_service.epub.write_epub", _partial_write)
    result, ingested = await _ingest({"url": BOOK_URL}, FixtureBookClient(), monkeypatch)

    doc = await _document(factory, result["document_id"])
    assert (doc.stage, doc.error_message) == (
        "error",
        "O'Reilly download failed: No space left on device",
    )
    ingested.assert_not_called()
    assert list((tmp_path / "raw").iterdir()) == []


@pytest.mark.asyncio
async def test_ingest_url_auto_detects_oreilly_unconfigured():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/documents/ingest-url",
            json={"url": "https://learning.oreilly.com/library/view/ddia/9781491903063/"},
        )
        # Without cookies configured, it immediately warns the user
        assert resp.status_code == 401
        assert "O'Reilly subscription cookies not configured" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_url_auto_detects_oreilly_configured():
    transport = ASGITransport(app=app)
    mock_result = {
        "document_id": "test-doc-1234",
        "status": "processing",
        "title": "Designing Data-Intensive Applications",
    }
    with patch(
        "app.routers.documents.start_oreilly_ingestion",
        return_value=mock_result,
    ) as mock_start:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/documents/ingest-url",
                json={"url": "https://learning.oreilly.com/library/view/ddia/9781491903063/"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["document_id"] == "test-doc-1234"
            assert data["status"] == "processing"
            mock_start.assert_called_once()
