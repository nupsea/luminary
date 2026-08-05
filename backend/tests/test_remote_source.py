"""A URL that points at a file must be ingested as that file, or refused.

The bug: a link to a PDF in a GitHub repository was fetched as an HTML page and
the site's navigation chrome was stored as the document, reporting success.
"""

import uuid

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app  # noqa: F401 (used via ASGITransport)
from app.models import DocumentModel
from app.services import remote_source
from app.services.remote_source import (
    RemoteDocumentTooLarge,
    UningestibleRemoteContent,
    canonical_source_url,
    fetch_remote_document,
)

MINIMAL_PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"

# What GitHub serves at a /blob/ URL: a shell whose text is all navigation.
GITHUB_BLOB_HTML = b"""<!doctype html><html><body>
<nav>Skip to content Navigation Menu Sign in Appearance settings Platform
GitHub Copilot Write better code with AI</nav></body></html>"""


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


@pytest.fixture
def serve(monkeypatch):
    """Answer every request from a routing table instead of the network."""
    requested: list[str] = []

    def _install(routes: dict[str, httpx.Response]):
        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            for prefix, response in routes.items():
                if str(request.url).startswith(prefix):
                    return response
            return httpx.Response(404)

        real_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(remote_source.httpx, "AsyncClient", factory)
        return requested

    return _install


# The URL rewrite


def test_github_blob_url_is_rewritten_to_the_raw_file():
    assert canonical_source_url(
        "https://github.com/owner/repo/blob/main/paper.pdf"
    ) == "https://raw.githubusercontent.com/owner/repo/main/paper.pdf"


def test_gitlab_blob_url_is_rewritten_to_the_raw_file():
    assert canonical_source_url(
        "https://gitlab.com/group/sub/project/-/blob/main/doc.pdf"
    ) == "https://gitlab.com/group/sub/project/-/raw/main/doc.pdf"


def test_an_ordinary_article_url_is_left_alone():
    url = "https://example.com/blog/how-we-built-it"
    assert canonical_source_url(url) == url


def test_a_github_url_that_is_not_a_blob_is_left_alone():
    url = "https://github.com/owner/repo/issues/40"
    assert canonical_source_url(url) == url


# What the fetch decides


async def test_a_pdf_behind_a_blob_url_is_fetched_from_the_raw_url(serve):
    requested = serve(
        {
            "https://raw.githubusercontent.com/": httpx.Response(
                200, content=MINIMAL_PDF, headers={"content-type": "application/pdf"}
            ),
            "https://github.com/": httpx.Response(
                200, content=GITHUB_BLOB_HTML, headers={"content-type": "text/html"}
            ),
        }
    )

    doc = await fetch_remote_document("https://github.com/owner/repo/blob/main/except.pdf")

    assert doc is not None
    assert doc.content == MINIMAL_PDF
    assert doc.format == "pdf"
    assert doc.filename == "except"
    assert requested == ["https://raw.githubusercontent.com/owner/repo/main/except.pdf"], (
        "the viewer page must never be fetched -- its chrome is what got stored as a document"
    )


async def test_a_pdf_served_as_octet_stream_is_still_recognised(serve):
    serve(
        {
            "https://": httpx.Response(
                200, content=MINIMAL_PDF, headers={"content-type": "application/octet-stream"}
            )
        }
    )

    doc = await fetch_remote_document("https://files.example.com/download?id=7")

    assert doc is not None, "the magic bytes decide, not the declared type"
    assert doc.format == "pdf"


async def test_an_html_page_is_left_to_the_article_extractor(serve):
    serve(
        {
            "https://": httpx.Response(
                200, content=b"<html><body><p>real prose</p></body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        }
    )

    assert await fetch_remote_document("https://example.com/blog/post") is None


async def test_plain_text_is_left_to_the_article_extractor(serve):
    serve(
        {
            "https://": httpx.Response(
                200, content=b"just prose", headers={"content-type": "text/plain"}
            )
        }
    )

    assert await fetch_remote_document("https://example.com/notes.txt") is None


async def test_a_word_document_is_refused_by_name(serve):
    serve(
        {
            "https://": httpx.Response(
                200,
                content=b"PK\x03\x04binary",
                headers={
                    "content-type": (
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document"
                    )
                },
            )
        }
    )

    with pytest.raises(UningestibleRemoteContent) as exc:
        await fetch_remote_document("https://example.com/report.docx")
    assert "Word document" in str(exc.value)


async def test_an_oversized_pdf_is_refused_rather_than_buffered(serve, monkeypatch):
    monkeypatch.setattr(remote_source, "_MAX_BYTES", 4096)
    serve(
        {
            "https://": httpx.Response(
                200,
                content=MINIMAL_PDF + b"\x00" * 20000,
                headers={"content-type": "application/pdf"},
            )
        }
    )

    with pytest.raises(RemoteDocumentTooLarge):
        await fetch_remote_document("https://example.com/huge.pdf")


async def test_an_unreachable_url_raises_rather_than_falling_through(serve):
    serve({"https://": httpx.Response(500)})

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_remote_document("https://example.com/gone.pdf")


# End to end through the endpoint


async def test_ingest_url_stores_a_linked_pdf_as_a_pdf(test_db, serve, monkeypatch):
    _engine, factory, tmp_path = test_db

    async def _mock_run_ingestion(document_id, file_path, fmt, content_type=None, **_kwargs):
        pass

    monkeypatch.setattr("app.routers.documents.run_ingestion", _mock_run_ingestion)
    serve(
        {
            "https://raw.githubusercontent.com/": httpx.Response(
                200, content=MINIMAL_PDF, headers={"content-type": "application/pdf"}
            )
        }
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/documents/ingest-url",
            json={"url": "https://github.com/owner/repo/blob/main/except.pdf"},
        )

    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["document_id"]

    async with factory() as session:
        doc = (
            await session.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        ).scalar_one()

    assert doc.format == "pdf", "a PDF stored as markdown is the bug this closes"
    assert doc.content_type == "technical"
    assert doc.source_url == "https://raw.githubusercontent.com/owner/repo/main/except.pdf"
    assert (tmp_path / "raw" / f"{doc_id}.pdf").read_bytes() == MINIMAL_PDF


async def test_ingest_url_refuses_a_linked_word_document_with_415(test_db, serve):
    serve(
        {
            "https://": httpx.Response(
                200,
                content=b"PK\x03\x04binary",
                headers={"content-type": "application/msword"},
            )
        }
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/documents/ingest-url", json={"url": "https://example.com/report.doc"}
        )

    assert resp.status_code == 415
    assert "upload the file" in resp.json()["detail"]


async def test_ingest_url_still_creates_an_article_for_a_web_page(test_db, serve, monkeypatch):
    """The article path must be untouched by the probe in front of it."""
    _engine, factory, _tmp = test_db

    async def _mock_run_ingestion(document_id, file_path, fmt, content_type=None, **_kwargs):
        pass

    monkeypatch.setattr("app.routers.documents.run_ingestion", _mock_run_ingestion)
    serve(
        {
            "https://": httpx.Response(
                200, content=b"<html></html>", headers={"content-type": "text/html"}
            )
        }
    )

    from app.types import ParsedDocument, Section

    class _Extractor:
        async def extract(self, url, doc_id=None):
            return ParsedDocument(
                title="A Real Article",
                format="md",
                pages=1,
                word_count=3,
                sections=[Section(heading="A Real Article", level=1, text="a b c",
                                  page_start=0, page_end=0)],
                raw_text="a b c",
                warnings=[],
            )

    monkeypatch.setattr("app.routers.documents.get_article_extractor", lambda: _Extractor())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/documents/ingest-url", json={"url": "https://example.com/blog/post"}
        )

    assert resp.status_code == 200, resp.text
    async with factory() as session:
        doc = (
            await session.execute(
                select(DocumentModel).where(DocumentModel.id == resp.json()["document_id"])
            )
        ).scalar_one()
    assert doc.format == "md"
    assert doc.content_type == "tech_article"
    assert doc.title == "A Real Article"


async def test_document_ids_are_distinct_per_ingest(test_db, serve, monkeypatch):
    """Guards the shared doc_id the PDF branch inherits from the article branch."""

    async def _mock_run_ingestion(document_id, file_path, fmt, content_type=None, **_kwargs):
        pass

    monkeypatch.setattr("app.routers.documents.run_ingestion", _mock_run_ingestion)
    serve(
        {
            "https://": httpx.Response(
                200, content=MINIMAL_PDF, headers={"content-type": "application/pdf"}
            )
        }
    )

    seen = set()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(2):
            resp = await client.post(
                "/documents/ingest-url", json={"url": "https://example.com/paper.pdf"}
            )
            assert resp.status_code == 200, resp.text
            seen.add(resp.json()["document_id"])

    assert len(seen) == 2
    assert all(uuid.UUID(s) for s in seen)
