"""Tests for S149 — EPUB chapter viewer endpoints and sanitizer.

Unit tests:
  - sanitize_html strips <script> and on* attributes; keeps <table>, <code>, <em>, <pre>
  - sanitize_html strips <iframe>

HTTP endpoint tests (in-memory DB + real EPUB fixture):
  - GET /documents/{id}/epub/toc: 404 for unknown document
  - GET /documents/{id}/epub/toc: 400 for non-EPUB document
  - GET /documents/{id}/epub/toc: 200 with 3 chapters for 3-chapter EPUB fixture
  - GET /documents/{id}/epub/chapter/0: 200 with non-empty sanitized HTML
  - GET /documents/{id}/epub/chapter/99: 404 out-of-range
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.services.epub_service import EpubService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_epub(chapters: int, tmp_dir: Path) -> Path:
    """Create a minimal EPUB with `chapters` chapters and return its path."""
    from ebooklib import epub  # type: ignore[import-untyped]

    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title("Test Book")
    book.set_language("en")

    items = []
    for i in range(chapters):
        ch = epub.EpubHtml(
            title=f"Chapter {i + 1}",
            file_name=f"chap{i + 1}.xhtml",
            lang="en",
        )
        ch.content = (
            f"<html><body>"
            f"<h1>Chapter {i + 1}</h1>"
            f"<p>Content of chapter {i + 1}. Lorem ipsum dolor sit amet consectetur.</p>"
            f"<table><tr><td>Cell A</td><td>Cell B</td></tr></table>"
            f"<code>code_here()</code>"
            f"<em>emphasis text</em>"
            f"<pre>preformatted block</pre>"
            f"</body></html>"
        ).encode()
        book.add_item(ch)
        items.append(ch)

    book.toc = tuple(
        epub.Link(f"chap{i + 1}.xhtml", f"Chapter {i + 1}", f"chap{i + 1}") for i in range(chapters)
    )
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + list(items)

    epub_path = tmp_dir / "test.epub"
    epub.write_epub(str(epub_path), book)
    return epub_path


# ---------------------------------------------------------------------------
# Test DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Unit tests — EpubService.sanitize_html
# ---------------------------------------------------------------------------


def test_sanitize_strips_script():
    """Script tags are removed entirely."""
    svc = EpubService()
    result = svc.sanitize_html("<p>Hello</p><script>alert('xss')</script><p>World</p>")
    assert "<script" not in result
    assert "alert" not in result
    assert "Hello" in result
    assert "World" in result


def test_sanitize_strips_iframe():
    """Iframe tags are removed."""
    svc = EpubService()
    result = svc.sanitize_html("<p>Content</p><iframe src='evil.html'></iframe>")
    assert "<iframe" not in result
    assert "Content" in result


def test_sanitize_strips_on_event_attributes():
    """on* event attributes are removed from allowed tags."""
    svc = EpubService()
    result = svc.sanitize_html('<p onclick="evil()">Hello</p>')
    assert "onclick" not in result
    assert "Hello" in result


def test_sanitize_keeps_table():
    """<table>, <tr>, <td>, <th> are preserved after sanitization."""
    svc = EpubService()
    html = "<table><thead><tr><th>H1</th></tr></thead><tbody><tr><td>Cell</td></tr></tbody></table>"
    result = svc.sanitize_html(html)
    assert "<table" in result
    assert "<td>" in result
    assert "<th>" in result


def test_sanitize_keeps_code_em_pre():
    """<code>, <em>, and <pre> are preserved after sanitization."""
    svc = EpubService()
    html = "<code>x = 1</code><em>italic</em><pre>block</pre>"
    result = svc.sanitize_html(html)
    assert "<code>" in result
    assert "<em>" in result
    assert "<pre>" in result


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_epub_toc_unknown_document(test_db):
    """GET /documents/{id}/epub/toc returns 404 for unknown document ID."""
    from httpx import ASGITransport, AsyncClient

    unknown_id = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{unknown_id}/epub/toc")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_epub_toc_non_epub_document(test_db):
    """GET /documents/{id}/epub/toc returns 400 for a non-EPUB document."""
    from httpx import ASGITransport, AsyncClient

    from app.models import DocumentModel

    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    txt_path = tmp_path / f"{doc_id}.txt"
    txt_path.write_text("Hello world")

    async with factory() as session:
        doc = DocumentModel(
            id=doc_id,
            title="Plain Text",
            format="txt",
            content_type="book",
            word_count=2,
            page_count=0,
            file_path=str(txt_path),
            file_hash=None,
            stage="complete",
        )
        session.add(doc)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/epub/toc")
    assert resp.status_code == 400
    assert "not an epub" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_epub_toc_three_chapters(test_db):
    """GET /documents/{id}/epub/toc returns 3 entries for a 3-chapter EPUB."""
    from httpx import ASGITransport, AsyncClient

    from app.models import DocumentModel

    # Clear epub_service LRU cache so each test gets a fresh instance
    from app.services.epub_service import get_epub_service

    get_epub_service.cache_clear()

    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    epub_path = _make_epub(3, tmp_path)

    async with factory() as session:
        doc = DocumentModel(
            id=doc_id,
            title="Test EPUB",
            format="epub",
            content_type="book",
            word_count=100,
            page_count=0,
            file_path=str(epub_path),
            file_hash=None,
            stage="complete",
        )
        session.add(doc)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/epub/toc")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["document_id"] == doc_id
    assert len(data["chapters"]) == 3
    assert data["chapters"][0]["chapter_index"] == 0
    assert "Chapter 1" in data["chapters"][0]["title"]


@pytest.mark.asyncio
async def test_epub_chapter_zero_returns_html(test_db):
    """GET /documents/{id}/epub/chapter/0 returns non-empty sanitized HTML."""
    from httpx import ASGITransport, AsyncClient

    from app.models import DocumentModel
    from app.services.epub_service import get_epub_service

    get_epub_service.cache_clear()

    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    epub_path = _make_epub(3, tmp_path)

    async with factory() as session:
        doc = DocumentModel(
            id=doc_id,
            title="Test EPUB",
            format="epub",
            content_type="book",
            word_count=100,
            page_count=0,
            file_path=str(epub_path),
            file_hash=None,
            stage="complete",
        )
        session.add(doc)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/epub/chapter/0")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["chapter_index"] == 0
    assert len(data["html"]) > 0
    # Sanitized HTML must keep prose tags
    assert "Chapter 1" in data["html"]
    # No scripts
    assert "<script" not in data["html"]


@pytest.mark.asyncio
async def test_epub_chapter_out_of_range(test_db):
    """GET /documents/{id}/epub/chapter/99 returns 404 for a 3-chapter EPUB."""
    from httpx import ASGITransport, AsyncClient

    from app.models import DocumentModel
    from app.services.epub_service import get_epub_service

    get_epub_service.cache_clear()

    _engine, factory, tmp_path = test_db
    doc_id = str(uuid.uuid4())
    epub_path = _make_epub(3, tmp_path)

    async with factory() as session:
        doc = DocumentModel(
            id=doc_id,
            title="Test EPUB",
            format="epub",
            content_type="book",
            word_count=100,
            page_count=0,
            file_path=str(epub_path),
            file_hash=None,
            stage="complete",
        )
        session.add(doc)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/documents/{doc_id}/epub/chapter/99")
    assert resp.status_code == 404
