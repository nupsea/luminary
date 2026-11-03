"""POST /documents/{id}/reparse.

A parser fix only reaches a document by parsing it again, and stored text cannot
be repaired in place. `/documents/ingest` deduplicates on `file_hash`, so
re-uploading the same file silently returns the old row -- which is why this
endpoint exists rather than "just upload it again".
"""

import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import AnnotationModel, ChunkModel, DocumentModel, SectionModel
from tests.factories import make_chunk, make_document, make_section


async def _seed(factory, tmp_path, *, with_url: bool) -> str:
    """A text file, or with `with_url` a web article: its extraction stored as Markdown."""
    doc_id = str(uuid.uuid4())
    raw = tmp_path / f"{doc_id}.{'md' if with_url else 'txt'}"
    raw.write_text("Some source text for the document.", encoding="utf-8")
    async with factory() as s:
        s.add(
            make_document(
                id=doc_id,
                title="Doc",
                word_count=6,
                format="md" if with_url else "txt",
                file_path=str(raw),
                source_url="https://example.test/post" if with_url else None,
            )
        )
        s.add(make_section(id="sec1", document_id=doc_id, heading="H", body="B"))
        s.add(make_chunk(id="chunk1", document_id=doc_id, section_id="sec1"))
        s.add(
            AnnotationModel(
                id="ann1",
                document_id=doc_id,
                section_id="sec1",
                selected_text="B",
                start_offset=0,
                end_offset=1,
            )
        )
        await s.commit()
    return doc_id


@pytest.mark.anyio
async def test_preview_changes_nothing_and_reports_the_cost(test_db):
    """Consent first. The preview call must not touch a single row."""
    _, factory, tmp_path = test_db
    doc_id = await _seed(factory, tmp_path, with_url=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/documents/{doc_id}/reparse", json={"confirm": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "preview"
    assert body["source"] == "file"
    # The highlight anchored to the old section is named, not silently stranded.
    assert body["anchored"]["annotations"] == 1
    assert body["detail"]

    async with factory() as s:
        assert await s.get(SectionModel, "sec1") is not None
        assert await s.get(ChunkModel, "chunk1") is not None


@pytest.mark.anyio
async def test_a_missing_original_is_refused_rather_than_half_done(test_db):
    """Clearing the old parse before discovering the source is gone destroys the document."""
    _, factory, tmp_path = test_db
    doc_id = await _seed(factory, tmp_path, with_url=False)
    async with factory() as s:
        doc = await s.get(DocumentModel, doc_id)
        doc.file_path = str(tmp_path / "gone.txt")
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/documents/{doc_id}/reparse", json={"confirm": True})
    assert r.status_code == 409
    async with factory() as s:
        assert await s.get(SectionModel, "sec1") is not None


@pytest.mark.anyio
async def test_a_url_backed_document_reports_the_url_as_its_source(test_db):
    """The stored raw file for an article is the old extraction, not the page.

    Re-parsing that file would re-read the corrupted output, so these must come
    from `source_url` instead.
    """
    _, factory, tmp_path = test_db
    doc_id = await _seed(factory, tmp_path, with_url=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/documents/{doc_id}/reparse", json={"confirm": False})
    assert r.json()["source"] == "url"


@pytest.mark.anyio
async def test_unknown_document_is_404(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/documents/{uuid.uuid4()}/reparse", json={"confirm": False})
    assert r.status_code == 404


@pytest.mark.anyio
async def test_a_confirmed_reparse_carries_the_render_and_refreshes_the_report(test_db):
    """The fidelity notice offers this button, so it must not degrade the page.

    Two defects met here. The extractor was called without `rendered_html`, so
    a page whose content its scripts produce came back static -- the notice
    naming missing figures would have cost the reader the rest of them. And the
    stored `extraction_report` was never rewritten, so the notice described the
    import it replaced, permanently.
    """
    _, factory, tmp_path = test_db
    doc_id = await _seed(factory, tmp_path, with_url=True)
    async with factory() as s:
        doc = await s.get(DocumentModel, doc_id)
        doc.extraction_report = {"dropped": {"diagram": 2}, "notes": []}
        await s.commit()

    seen: dict[str, object] = {}

    class _Parsed:
        title = "T"
        format = "html"
        pages = 1
        word_count = 3
        sections = []
        raw_text = "new text"
        extraction_report = {"dropped": {}, "notes": ["clean"]}

    class _Extractor:
        async def extract(self, url, doc_id=None, rendered_html=None):
            seen["url"] = url
            seen["rendered_html"] = rendered_html
            return _Parsed()

    import app.routers.documents as documents_router

    original = documents_router.get_article_extractor
    documents_router.get_article_extractor = lambda: _Extractor()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(
                f"/documents/{doc_id}/reparse",
                json={"confirm": True, "rendered_html": "<html>rendered</html>"},
            )
    finally:
        documents_router.get_article_extractor = original

    assert r.status_code == 200
    assert seen["rendered_html"] == "<html>rendered</html>"
    async with factory() as s:
        doc = await s.get(DocumentModel, doc_id)
        assert doc.extraction_report == {"dropped": {}, "notes": ["clean"]}


@pytest.fixture
def network_refused(monkeypatch):
    """Every outbound connection fails, so a re-import that reaches for one fails too."""
    import socket

    attempts: list[object] = []

    def _refuse(self, address, *_a, **_k):
        attempts.append(address)
        raise OSError("network refused by the test")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    return attempts


def _record_ingestion(monkeypatch) -> list[tuple]:
    calls: list[tuple] = []

    async def _ingest(doc_id, file_path, fmt, parsed_document=None, **_k):
        calls.append((doc_id, file_path, fmt, parsed_document))

    monkeypatch.setattr("app.routers.documents.run_ingestion", _ingest)
    return calls


def _refuse_article_fetch(monkeypatch) -> None:
    class _NoFetch:
        async def extract(self, *_a, **_k):
            raise AssertionError("a stored source was re-fetched as a web article")

    monkeypatch.setattr("app.routers.documents.get_article_extractor", lambda: _NoFetch())


async def _confirm_reparse(doc_id: str) -> dict:
    from app.services.ingestion_jobs import get_ingestion_jobs

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/documents/{doc_id}/reparse", json={"confirm": True})
    assert r.status_code == 200, r.text
    await get_ingestion_jobs().get(doc_id)
    return r.json()


@pytest.mark.anyio
async def test_an_oreilly_book_is_reparsed_from_its_stored_epub_offline(
    test_db, monkeypatch, network_refused
):
    """#430: the book URL sent re-import through the article extractor, fetching oreilly.com."""
    from app.services.oreilly_service import download_oreilly_book_to_epub
    from app.workflows.ingestion_nodes.parse import parse_node
    from tests.oreilly_book import BOOK_ID, BOOK_URL, FixtureBookClient

    _, factory, tmp_path = test_db
    epub_path, _ = download_oreilly_book_to_epub(
        BOOK_ID, tmp_path / "book.epub", FixtureBookClient()
    )
    async with factory() as s:
        s.add(
            make_document(
                id="book",
                title="Fixture Systems",
                format="epub",
                file_path=str(epub_path),
                source_url=BOOK_URL,
            )
        )
        await s.commit()
    _refuse_article_fetch(monkeypatch)
    calls = _record_ingestion(monkeypatch)

    result = await _confirm_reparse("book")

    assert result["source"] == "file"
    assert calls == [("book", str(epub_path), "epub", None)]
    parsed = await parse_node(
        {"document_id": "book", "file_path": str(epub_path), "format": "epub"}
    )
    assert [s["heading"] for s in parsed["parsed_document"]["sections"]][:2] == [
        "Preface",
        "1. Storage",
    ]
    assert network_refused == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("fmt", "url"),
    [("flac", "https://www.youtube.com/watch?v=t1"), ("pdf", "https://example.test/paper.pdf")],
    ids=["youtube-talk", "linked-pdf"],
)
async def test_a_stored_media_or_pdf_source_is_reread_offline(
    test_db, monkeypatch, network_refused, fmt, url
):
    _, factory, tmp_path = test_db
    stored = tmp_path / f"doc.{fmt}"
    stored.write_bytes(b"stored source")
    async with factory() as s:
        s.add(make_document(id="doc", format=fmt, file_path=str(stored), source_url=url))
        await s.commit()
    _refuse_article_fetch(monkeypatch)
    calls = _record_ingestion(monkeypatch)

    result = await _confirm_reparse("doc")

    assert result["source"] == "file"
    assert calls == [("doc", str(stored), fmt, None)]
    assert network_refused == []


@pytest.mark.anyio
async def test_a_reimported_article_is_parsed_from_the_page_fetched_again(test_db, monkeypatch):
    """#430: the fresh extraction was handed to a graph that parses `file_path`, so the
    re-import re-read the old stored Markdown and the re-fetch changed nothing."""
    from app.services.parser import DocumentParser

    _, factory, tmp_path = test_db
    doc_id = await _seed(factory, tmp_path, with_url=True)
    fresh = "# Replication\n\n" + "Every write goes to the leader, which streams it on. " * 3

    class _Parsed:
        title, format, pages, word_count = "Doc", "md", 1, 30
        sections: list = []
        raw_text = fresh
        extraction_report = {"dropped": {}, "notes": []}

    class _Extractor:
        async def extract(self, *_a, **_k):
            return _Parsed()

    monkeypatch.setattr("app.routers.documents.get_article_extractor", lambda: _Extractor())
    calls = _record_ingestion(monkeypatch)

    result = await _confirm_reparse(doc_id)

    assert result["source"] == "url"
    ((_, file_path, fmt, _),) = calls
    # What the graph's parse node reads: the stored file, whatever else it is handed.
    parsed = DocumentParser().parse(Path(file_path), fmt)
    assert "Every write goes to the leader" in parsed.raw_text
    assert "Some source text" not in parsed.raw_text
