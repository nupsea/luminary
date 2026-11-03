"""Integration tests for O'Reilly router and auto-detection in /documents/ingest-url."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import DocumentModel
from app.services.ingestion_jobs import get_ingestion_jobs
from app.services.oreilly_service import delete_oreilly_cookies, save_oreilly_cookies
from tests.oreilly_book import BOOK_ID, BOOK_URL, METADATA, FixtureBookClient


@pytest.fixture(autouse=True)
def clean_cookies():
    delete_oreilly_cookies()
    yield
    delete_oreilly_cookies()


@pytest.mark.asyncio
async def test_oreilly_status_unconfigured():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/oreilly/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data["valid"] is False


@pytest.mark.asyncio
async def test_oreilly_set_cookies_invalid():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Empty cookies
        resp = await client.post("/oreilly/cookies", json={"cookies": ""})
        assert resp.status_code == 400

        # 2. Cookies that fail session validation
        with patch(
            "app.services.oreilly_service.OreillyClient.validate_session",
            return_value=(False, "Expired"),
        ):
            resp = await client.post("/oreilly/cookies", json={"cookies": "_abck=badtoken"})
            assert resp.status_code == 401


@pytest.mark.asyncio
async def test_oreilly_set_cookies_valid_and_status():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "app.services.oreilly_service.OreillyClient.validate_session",
            return_value=(True, "learner@example.com"),
        ):
            resp = await client.post(
                "/oreilly/cookies",
                json={"cookies": [{"name": "_abck", "value": "goodtoken"}]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["valid"] is True
            assert data["user"] == "learner@example.com"

        # Check status now reflects active configuration
        with patch(
            "app.services.oreilly_service.OreillyClient.validate_session",
            return_value=(True, "learner@example.com"),
        ):
            resp = await client.get("/oreilly/status")
            assert resp.status_code == 200
            assert resp.json()["configured"] is True
            assert resp.json()["valid"] is True

        # Delete cookies
        resp = await client.delete("/oreilly/cookies")
        assert resp.status_code == 200

        resp = await client.get("/oreilly/status")
        assert resp.json()["configured"] is False


@pytest.mark.asyncio
async def test_oreilly_status_reports_an_expired_session():
    save_oreilly_cookies({"_abck": "stale"})
    with patch(
        "app.services.oreilly_service.OreillyClient.validate_session",
        return_value=(False, "Session expired or invalid (HTTP 302)"),
    ):
        async with _client() as client:
            resp = await client.get("/oreilly/status")
    assert resp.json() == {
        "configured": True,
        "valid": False,
        "user": None,
        "error": "Session expired or invalid (HTTP 302)",
    }


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _signed_in(module: str, book: FixtureBookClient):
    """`module`'s OreillyClient() returns the fixture book, as a stored session would."""
    return patch(f"{module}.OreillyClient", lambda *_a, **_k: book)


@pytest.mark.asyncio
async def test_oreilly_preview_lists_the_books_chapters():
    with _signed_in("app.routers.oreilly", FixtureBookClient()):
        async with _client() as client:
            resp = await client.post("/oreilly/preview", json={"url": BOOK_URL})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "book_id": BOOK_ID,
        "title": "Fixture Systems",
        "authors": ["Ada Author"],
        "description": METADATA["description"],
        "cover_url": METADATA["cover_url"],
        "chapter_count": 3,
        "chapters": [
            {"index": 0, "title": "Preface", "minutes_required": 3.5},
            {"index": 1, "title": "1. Storage", "minutes_required": 12.0},
            {"index": 2, "title": "2. Replication", "minutes_required": 15.25},
        ],
    }


@pytest.mark.asyncio
async def test_oreilly_preview_refuses_a_url_without_a_book_id():
    async with _client() as client:
        resp = await client.post("/oreilly/preview", json={"url": "not a book"})
    assert resp.status_code == 400
    assert "book identifier" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_oreilly_preview_failure_names_the_cause():
    book = FixtureBookClient()

    def _reset(_book_id):
        raise ConnectionError("reset by peer")

    book.fetch_chapter_list = _reset
    with _signed_in("app.routers.oreilly", book):
        async with _client() as client:
            resp = await client.post("/oreilly/preview", json={"url": BOOK_URL})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to fetch book preview: reset by peer"


async def _ingest(body: dict, book: FixtureBookClient, monkeypatch) -> tuple[dict, AsyncMock]:
    """POST /oreilly/ingest and wait for its job; the ingestion graph itself is not run."""
    ingested = AsyncMock()
    monkeypatch.setattr("app.workflows.oreilly_ingestion.run_ingestion", ingested)
    with _signed_in("app.workflows.oreilly_ingestion", book):
        async with _client() as client:
            resp = await client.post("/oreilly/ingest", json=body)
            assert resp.status_code == 200, resp.text
            await get_ingestion_jobs().get(resp.json()["document_id"])
    return resp.json(), ingested


async def _document(factory, doc_id: str) -> DocumentModel:
    async with factory() as session:
        return await session.get(DocumentModel, doc_id)


@pytest.mark.asyncio
async def test_oreilly_ingest_without_a_session_opens_the_connect_modal(test_db):
    _, factory, _ = test_db
    async with _client() as client:
        resp = await client.post("/oreilly/ingest", json={"url": BOOK_URL})
    assert resp.status_code == 401
    assert "O'Reilly subscription cookies not configured" in resp.json()["detail"]
    async with factory() as session:
        assert (await session.scalars(select(DocumentModel))).all() == []


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
async def test_oreilly_ingest_downloads_only_the_selected_chapters(test_db, monkeypatch):
    _, factory, _ = test_db
    book = FixtureBookClient()
    result, _ = await _ingest({"url": BOOK_URL, "selected_chapters": [1]}, book, monkeypatch)

    assert [u.rsplit("/", 1)[-1] for u in book.fetched if u.endswith(".html")] == ["ch01.html"]
    doc = await _document(factory, result["document_id"])
    assert (doc.title, doc.tags) == ("Fixture Systems", ["oreilly", "tech-book"])


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
async def test_oreilly_preview_unconfigured():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/oreilly/preview",
            json={"url": "https://learning.oreilly.com/library/view/ddia/9781491903063/"},
        )
        assert resp.status_code == 401


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
