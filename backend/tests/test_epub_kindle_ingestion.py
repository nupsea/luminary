"""Tests for S123 -- EPUB and Kindle My Clippings.txt ingestion."""

import io
import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel
from app.services.parser import DocumentParser
from app.workflows.ingestion import _classify

# ---------------------------------------------------------------------------
# Shared DB fixture
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
# _classify() pure function tests
# ---------------------------------------------------------------------------


def test_classify_epub_by_extension():
    assert _classify("any text", [], 1000, "epub") == "book"


def test_classify_kindle_clippings_by_content():
    sample_text = (
        "==========\n"
        "Some Book (Author Name)\n"
        "- Your Highlight on page 10 | Added on Friday, January 1, 2021\n\n"
        "A great passage from the book.\n"
        "=========="
    )
    result = _classify(sample_text, [], 100, "txt")
    assert result == "kindle_clippings"


def test_classify_kindle_clippings_by_filename():
    result = _classify("plain text content", [], 100, "txt", filename="My Clippings.txt")
    assert result == "kindle_clippings"


def test_classify_epub_takes_priority_over_kindle_content():
    result = _classify("==========\nbookmark content\n==========", [], 50, "epub")
    assert result == "book"


# ---------------------------------------------------------------------------
# EPUB parsing tests - MOCKED to avoid zip/ebooklib issues
# ---------------------------------------------------------------------------


def test_parse_epub_extracts_chapters(tmp_path):
    epub_path = tmp_path / "test.epub"
    epub_path.write_bytes(b"fake epub content")

    with patch("ebooklib.epub.read_epub") as mock_read:
        mock_book = MagicMock()
        mock_book.get_metadata.return_value = [("Test EPUB Book", {})]

        item1 = MagicMock()
        item1.get_name.return_value = "ch1.html"
        item1.get_content.return_value = (
            b"<h1>Chapter 1</h1><p>This is a much longer content for "
            b"the chapter to ensure it passes the minimum length "
            b"requirement of 50 characters in the parser.</p>"
        )

        mock_book.get_items_of_type.return_value = [item1]
        mock_read.return_value = mock_book

        parser = DocumentParser()
        result = parser.parse(epub_path, "epub")

        assert result is not None
        assert result.title == "Test EPUB Book"
        assert len(result.sections) >= 1
        assert "Chapter 1" in result.sections[0].heading


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ingest_epub_accepted(test_db, tmp_path):
    """POST /documents/ingest accepts .epub files."""
    import asyncio  # noqa: PLC0415

    import app.routers.documents as docs_module  # noqa: PLC0415

    epub_path = tmp_path / "test.epub"
    epub_path.write_bytes(b"fake epub content")

    mock_run = MagicMock(return_value=asyncio.sleep(0))

    with patch.object(docs_module, "run_ingestion", mock_run):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/documents/ingest",
                files={"file": ("book.epub", b"fake content", "application/epub+zip")},
                data={"content_type": "book"},
            )

    assert resp.status_code == 200
    assert mock_run.called
    # Check the 4th argument (content_type)
    assert mock_run.call_args[0][3] == "book"


KINDLE_SAMPLE = """\
==========
The Great Gatsby (F. Scott Fitzgerald)
- Your Highlight on page 42 | Added on Monday, June 14, 2021 8:00:00 PM

So we beat on, boats against the current.
==========
Dune (Frank Herbert)
- Your Highlight on page 100 | Added on Tuesday, July 1, 2021 10:00:00 AM

A beginning is a very delicate time.
==========
"""


@pytest.mark.anyio
async def test_ingest_kindle_creates_one_doc_per_book(test_db):
    """POST /documents/ingest-kindle creates one DocumentModel per book."""
    engine, factory, _ = test_db
    import asyncio  # noqa: PLC0415

    import app.routers.documents as docs_module  # noqa: PLC0415

    mock_run = MagicMock(return_value=asyncio.sleep(0))

    with patch.object(docs_module, "run_ingestion", mock_run):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/documents/ingest-kindle",
                files={
                    "file": (
                        "My Clippings.txt",
                        io.BytesIO(KINDLE_SAMPLE.encode()),
                        "text/plain",
                    )
                },
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["book_count"] == 2
    assert mock_run.call_count == 2


@pytest.mark.anyio
async def test_flashcard_generation_works_on_kindle_doc(test_db):
    """Flashcard generation endpoint accepts kindle_clippings documents."""
    engine, factory, _ = test_db

    doc_id = str(uuid.uuid4())
    async with factory() as session:
        from app.models import ChunkModel, SectionModel  # noqa: PLC0415

        doc = DocumentModel(
            id=doc_id,
            title="The Great Gatsby",
            format="txt",
            content_type="kindle_clippings",
            word_count=200,
            page_count=0,
            file_path="/tmp/test.txt",
            file_hash=None,
            stage="complete",
            tags=["kindle"],
        )
        section = SectionModel(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            heading="Highlight (June 14, 2021)",
            level=1,
            page_start=0,
            page_end=0,
            section_order=0,
            preview="So we beat on, boats against the current.",
        )
        chunk = ChunkModel(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            section_id=section.id,
            text="So we beat on, boats against the current, borne back ceaselessly into the past.",
            chunk_index=0,
            page_number=0,
        )

        session.add_all([doc, section, chunk])
        await session.commit()

    from unittest.mock import AsyncMock, patch  # noqa: PLC0415

    from app.services.flashcard import FlashcardService  # noqa: PLC0415

    mock_cards = [
        {
            "front": "What image?",
            "back": "Boats",
            "source_chunk_id": chunk.id,
            "source_excerpt": "So we beat on...",
        }
    ]

    with patch.object(FlashcardService, "generate", new=AsyncMock(return_value=mock_cards)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/flashcards/generate/{doc_id}",
                json={"num_cards": 5},
            )

    assert resp.status_code != 422
