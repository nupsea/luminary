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
    item = resp.json()["items"][0]
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
    return resp.json()["items"][0]


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
    assert content.json()["items"][0]["content"] == long_text


async def _seed_sections(factory, doc_id: str, bodies: list[str]) -> list[str]:
    ids = []
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Manual",
                format="pdf",
                content_type="tech_book",
                word_count=10,
                page_count=5,
                file_path="/tmp/m.pdf",
                stage="complete",
            )
        )
        for i, body in enumerate(bodies):
            sid = str(uuid.uuid4())
            ids.append(sid)
            session.add(
                SectionModel(
                    id=sid,
                    document_id=doc_id,
                    heading=f"S{i}",
                    level=1,
                    page_start=i,
                    page_end=i,
                    section_order=i,
                    body=body,
                )
            )
        await session.commit()
    return ids


@pytest.mark.asyncio
async def test_the_window_is_bounded_and_says_how_much_it_left(test_db):
    """Unbounded, this returned 20.2 MB over 1,017 sections on one manual.

    Enough for a browser to report the page as unresponsive, which is how it
    was found.
    """
    factory = test_db
    doc_id = str(uuid.uuid4())
    await _seed_sections(factory, doc_id, [f"body {i}" for i in range(10)])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = (await client.get(f"/sections/{doc_id}/content?offset=2&limit=3")).json()

    assert [i["heading"] for i in page["items"]] == ["S2", "S3", "S4"]
    assert page["total"] == 10, "total counts the document, not the window"
    assert page["offset"] == 2
    assert page["limit"] == 3


@pytest.mark.asyncio
async def test_a_huge_section_is_shortened_but_never_silently(test_db):
    """A bound on the output is only honest when the rest stays reachable.

    One section of the manual holds 5,063,040 characters, so the list cannot
    carry it. `content_chars` is the length of the whole section, which is what
    tells a client the text is shortened rather than short.
    """
    factory = test_db
    doc_id = str(uuid.uuid4())
    huge = "x" * 90_000
    ids = await _seed_sections(factory, doc_id, [huge, "short one"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = (await client.get(f"/sections/{doc_id}/content")).json()
        whole = (await client.get(f"/sections/{doc_id}/content/{ids[0]}")).json()

    big, small = page["items"]
    assert big["truncated"] is True
    assert big["content_chars"] == 90_000, "the full length, not the served length"
    assert len(big["content"]) < 90_000

    assert small["truncated"] is False
    assert small["content_chars"] == len("short one")

    # The other half of the bargain: the whole section is one call away.
    assert whole["truncated"] is False
    assert len(whole["content"]) == 90_000


@pytest.mark.asyncio
async def test_content_is_not_read_as_a_document_id(test_db):
    """`content/{section_id}` is declared above the windowed route."""
    factory = test_db
    doc_id = str(uuid.uuid4())
    ids = await _seed_sections(factory, doc_id, ["only body"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.get(f"/sections/{doc_id}/content/{ids[0]}")
        missing = await client.get(f"/sections/{doc_id}/content/{uuid.uuid4()}")

    assert ok.status_code == 200
    assert ok.json()["heading"] == "S0"
    assert missing.status_code == 404
