"""Unit tests for GET /documents/{id}/search endpoint (S151).

Three tests:
1. Returns matching sections with snippet for a known query.
2. Sections from a different document are NOT returned.
3. Empty query (q='') returns [] with HTTP 200.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, SectionModel


@pytest_asyncio.fixture
async def _search_test_db(tmp_path, monkeypatch):
    """Isolated in-memory SQLite with two documents and FTS rows for isolation tests."""
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

    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)

    # Insert doc1 with a chunk containing "fox" using ORM (respects column defaults)
    async with factory() as session:
        doc1 = DocumentModel(
            id="doc1",
            title="Test Doc",
            format="txt",
            content_type="book",
            word_count=100,
            page_count=1,
            file_path=str(tmp_path / "raw" / "doc1.txt"),
            stage="complete",
        )
        sec1 = SectionModel(
            id="sec1",
            document_id="doc1",
            heading="Chapter One",
            level=1,
            section_order=0,
            preview="The quick brown fox",
        )
        chunk1 = ChunkModel(
            id="chunk1",
            document_id="doc1",
            section_id="sec1",
            text="The quick brown fox jumps",
            token_count=5,
            chunk_index=0,
        )
        # doc2 with "dog" — must not appear when searching doc1
        doc2 = DocumentModel(
            id="doc2",
            title="Other Doc",
            format="txt",
            content_type="book",
            word_count=100,
            page_count=1,
            file_path=str(tmp_path / "raw" / "doc2.txt"),
            stage="complete",
        )
        sec2 = SectionModel(
            id="sec2",
            document_id="doc2",
            heading="Chapter Two",
            level=1,
            section_order=0,
            preview="Lazy dog",
        )
        chunk2 = ChunkModel(
            id="chunk2",
            document_id="doc2",
            section_id="sec2",
            text="The lazy dog sits",
            token_count=4,
            chunk_index=0,
        )
        session.add_all([doc1, sec1, chunk1, doc2, sec2, chunk2])
        await session.commit()

        # Insert FTS rows using raw SQL (FTS5 virtual table not mapped by ORM)
        await session.execute(
            text(
                "INSERT INTO chunks_fts (text, chunk_id, document_id)"
                " VALUES ('The quick brown fox jumps', 'chunk1', 'doc1')"
            )
        )
        await session.execute(
            text(
                "INSERT INTO chunks_fts (text, chunk_id, document_id)"
                " VALUES ('The lazy dog sits', 'chunk2', 'doc2')"
            )
        )
        await session.commit()

    yield

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_search_returns_matching_section(_search_test_db):
    """GET /documents/doc1/search?q=fox returns sec1 with a snippet."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents/doc1/search?q=fox")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    section_ids = [r["section_id"] for r in data]
    assert "sec1" in section_ids
    # Snippet must contain the matched term (with or without <mark> tags)
    hit = next(r for r in data if r["section_id"] == "sec1")
    assert "fox" in hit["snippet"].lower()
    assert hit["match_count"] >= 1


@pytest.mark.asyncio
async def test_search_excludes_other_document(_search_test_db):
    """Sections from doc2 are not returned when searching doc1.

    'dog' exists only in doc2 chunks; querying doc1 must return [].
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents/doc1/search?q=dog")
    assert resp.status_code == 200
    data = resp.json()
    assert data == [], f"Expected [], got {data}"


@pytest.mark.asyncio
async def test_empty_query_returns_200_empty_list(_search_test_db):
    """Empty query string q='' returns HTTP 200 with [] (not 422)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/documents/doc1/search?q=")
    assert resp.status_code == 200
    assert resp.json() == []
