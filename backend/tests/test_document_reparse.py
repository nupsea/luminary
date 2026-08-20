"""POST /documents/{id}/reparse.

A parser fix only reaches a document by parsing it again, and stored text cannot
be repaired in place. `/documents/ingest` deduplicates on `file_hash`, so
re-uploading the same file silently returns the old row -- which is why this
endpoint exists rather than "just upload it again".
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import AnnotationModel, ChunkModel, DocumentModel, SectionModel


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    yield engine, factory, tmp_path
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    get_settings.cache_clear()
    await engine.dispose()


async def _seed(factory, tmp_path, *, with_url: bool) -> str:
    doc_id = str(uuid.uuid4())
    raw = tmp_path / f"{doc_id}.txt"
    raw.write_text("Some source text for the document.", encoding="utf-8")
    async with factory() as s:
        s.add(
            DocumentModel(
                id=doc_id,
                title="Doc",
                format="txt",
                content_type="book",
                word_count=6,
                page_count=0,
                file_path=str(raw),
                stage="complete",
                tags=[],
                source_url="https://example.test/post" if with_url else None,
            )
        )
        s.add(
            SectionModel(
                id="sec1",
                document_id=doc_id,
                heading="H",
                level=1,
                section_order=0,
                body="B",
            )
        )
        s.add(
            ChunkModel(
                id="chunk1", document_id=doc_id, section_id="sec1", text="t", chunk_index=0
            )
        )
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
