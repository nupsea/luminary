"""GET /sections/{id}/content: which tier serves reading text, markdown hazards,
and page range.

Document text is rendered as markdown by the reader, so layout artifacts from a
PDF text layer can be read as markup. A hyphen left alone on its own line turned
whole sentences into headings in the reader.

The tier tests enforce I-29: reading text comes from `sections.body`, never from
retrieval chunks while a lossless source exists.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, SectionModel
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


async def _seed(factory, *, body: str, preview: str, chunks: tuple[str, ...] = ()) -> str:
    doc_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Novel",
                format="txt",
                content_type="book",
                word_count=10,
                page_count=0,
                file_path="/tmp/n.txt",
                stage="complete",
            )
        )
        session.add(
            SectionModel(
                id=section_id,
                document_id=doc_id,
                heading="Chapter I",
                level=1,
                page_start=0,
                page_end=0,
                section_order=0,
                body=body,
                preview=preview,
            )
        )
        for idx, text in enumerate(chunks):
            session.add(
                ChunkModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    section_id=section_id,
                    text=text,
                    chunk_index=idx,
                )
            )
        await session.commit()
    return doc_id


async def _content(doc_id: str) -> dict:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/sections/{doc_id}/content")
    assert resp.status_code == 200
    return resp.json()[0]


@pytest.mark.asyncio
async def test_body_wins_over_the_lossy_tiers(test_db):
    """A section longer than the preview cap reads from `body`, not from chunks.

    This is the whole point of the column: the cap used to divert every long
    chapter to chunk reassembly, which cuts mid-sentence and duplicates the
    overlap.
    """
    prose = "Tell me, O Muse, of that ingenious hero. " * 400  # past PREVIEW_CHARS
    doc_id = await _seed(
        test_db,
        body=prose,
        preview=prose[:10000],
        chunks=("[Novel > Chapter I] Tell me, O Muse, of that", "ingenious hero."),
    )

    item = await _content(doc_id)

    assert item["content_source"] == "body"
    assert item["content"] == prose
    assert "[Novel > Chapter I]" not in item["content"]


@pytest.mark.asyncio
async def test_chunks_serve_only_when_no_lossless_source_survives(test_db):
    """Sections stored before `body` existed, whose preview hit the cap."""
    doc_id = await _seed(
        test_db,
        body="",
        preview="x" * 10000,
        chunks=("[Novel > Chapter I] first half", "second half"),
    )

    item = await _content(doc_id)

    assert item["content_source"] == "chunks"
    assert item["content"] == "first half\n\nsecond half"


@pytest.mark.asyncio
async def test_short_legacy_section_reads_from_preview_not_chunks(test_db):
    """An uncapped preview is the original text, so it outranks reassembly."""
    doc_id = await _seed(
        test_db,
        body="",
        preview="A short chapter.",
        chunks=("[Novel > Chapter I] A short", "chapter."),
    )

    item = await _content(doc_id)

    assert item["content_source"] == "preview"
    assert item["content"] == "A short chapter."


@pytest.mark.asyncio
async def test_document_detail_caps_preview_but_reader_stays_uncapped(test_db):
    """DocumentDetail ships one preview per section; the reader endpoint does not.

    Opening a 210-section book sent 1.6 MB, 1.5 MB of it preview, for a field
    the section list renders under line-clamp-2.
    """
    from app.routers.documents import WIRE_PREVIEW_CHARS

    long_text = "The chapter continues at length. " * 400
    doc_id = await _seed(test_db, body=long_text, preview=long_text[:10000])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        detail = await client.get(f"/documents/{doc_id}")
        content = await client.get(f"/sections/{doc_id}/content")

    assert len(detail.json()["sections"][0]["preview"]) == WIRE_PREVIEW_CHARS
    # Reading text is untouched by the cap (I-29).
    assert content.json()[0]["content"] == long_text
