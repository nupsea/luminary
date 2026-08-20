"""GET /documents/facets.

The library offered filters that could match nothing -- `code` is not a storable
content type at all, `epub` is a format no document carries as its type -- and a
client cannot tell an empty filter from an empty page without asking the server.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import DocumentModel


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_session_factory", factory)
    yield engine, factory
    await engine.dispose()


async def _seed(factory, rows: list[tuple[str, str]]) -> None:
    async with factory() as s:
        for content_type, fmt in rows:
            s.add(
                DocumentModel(
                    id=str(uuid.uuid4()),
                    title=f"{content_type}-{fmt}",
                    content_type=content_type,
                    format=fmt,
                    file_path="/tmp/x",
                    stage="complete",
                )
            )
        await s.commit()


@pytest.mark.anyio
async def test_counts_come_from_the_whole_library(test_db):
    _, factory = test_db
    await _seed(
        factory,
        [("book", "pdf"), ("book", "epub"), ("tech_article", "md"), ("audio", "wav")],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/documents/facets")).json()

    assert body["content_types"] == {"book": 2, "tech_article": 1, "audio": 1}
    assert body["formats"] == {"pdf": 1, "epub": 1, "md": 1, "wav": 1}
    assert body["total"] == 4


@pytest.mark.anyio
async def test_a_type_with_no_documents_is_absent_rather_than_zero(test_db):
    """The caller renders what it is given, so a dead filter must not appear.

    Reporting `{"code": 0}` would put the choice back on every client, and the
    clients are what got this wrong in the first place.
    """
    _, factory = test_db
    await _seed(factory, [("book", "pdf")])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/documents/facets")).json()

    assert "code" not in body["content_types"]
    assert "kindle_clippings" not in body["content_types"]


@pytest.mark.anyio
async def test_facets_is_not_read_as_a_document_id(test_db):
    """`/documents/{id}` is declared after this route; order is what makes it work."""
    _, factory = test_db
    await _seed(factory, [("book", "pdf")])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/documents/facets")
    assert r.status_code == 200
    assert "content_types" in r.json()


@pytest.mark.anyio
async def test_an_empty_library_reports_nothing_rather_than_failing(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/documents/facets")).json()
    assert body == {"content_types": {}, "formats": {}, "total": 0}
