"""GET /sections/{id}/content: markdown hazards in extracted text, and page range.

Document text is rendered as markdown by the reader, so layout artifacts from a
PDF text layer can be read as markup. A hyphen left alone on its own line turned
whole sentences into headings in the reader.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel, SectionModel
from app.routers.sections import _reader_safe


class TestReaderSafe:
    def test_hyphen_under_prose_no_longer_forms_a_heading(self):
        assert _reader_safe("should be just\n-\nthis is what we are missing") == (
            "should be just\n\n-\nthis is what we are missing"
        )

    def test_equals_underline_is_also_neutralised(self):
        assert _reader_safe("Some prose\n===\nmore") == "Some prose\n\n===\nmore"

    def test_deliberate_horizontal_rule_is_preserved(self):
        assert _reader_safe("para one\n\n---\n\npara two") == "para one\n\n---\n\npara two"

    def test_list_items_are_untouched(self):
        assert _reader_safe("- first\n- second") == "- first\n- second"

    def test_empty_text_passes_through(self):
        assert _reader_safe("") == ""


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    yield factory
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    get_settings.cache_clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_content_endpoint_exposes_page_range_and_sanitises(test_db):
    """The reader needs page_start/page_end to place figures beside their text."""
    factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Paper",
                format="pdf",
                content_type="paper",
                word_count=10,
                page_count=5,
                file_path="/tmp/p.pdf",
                stage="complete",
            )
        )
        session.add(
            SectionModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                heading="Results",
                level=1,
                page_start=3,
                page_end=4,
                section_order=0,
                preview="trailing prose\n-\nfollowing line",
            )
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/sections/{doc_id}/content")

    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["page_start"] == 3
    assert item["page_end"] == 4
    assert "trailing prose\n\n-" in item["content"]
