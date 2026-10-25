"""GET /documents/facets.

The library offered filters that could match nothing -- `code` was not a storable
content type at all, `epub` is a format no document carried as its type -- and a
client cannot tell an empty filter from an empty page without asking the server.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.factories import make_document


@pytest.fixture
def test_db(memory_db):
    return memory_db.engine, memory_db.factory


async def _seed(factory, rows: list[tuple[str, str, str]]) -> None:
    async with factory() as s:
        for fmt, form, domain in rows:
            s.add(
                make_document(
                    title=f"{fmt}-{form}", format=fmt, form=form, domain=domain, file_path="/tmp/x"
                )
            )
        await s.commit()


@pytest.mark.anyio
async def test_counts_come_from_the_whole_library(test_db):
    _, factory = test_db
    await _seed(
        factory,
        [
            ("pdf", "prose", "general"),
            ("epub", "prose", "general"),
            ("md", "article", "technical"),
            ("wav", "dialogue", "technical"),
        ],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/documents/facets")).json()

    assert body["kinds"] == {"book": 2, "technical": 1, "audio": 1}
    assert body["formats"] == {"pdf": 1, "epub": 1, "md": 1, "wav": 1}
    assert body["total"] == 4


@pytest.mark.anyio
async def test_a_kind_with_no_documents_is_absent_rather_than_zero(test_db):
    """The caller renders what it is given, so a dead filter must not appear.

    Reporting `{"code": 0}` would put the choice back on every client, and the
    clients are what got this wrong in the first place.
    """
    _, factory = test_db
    await _seed(factory, [("pdf", "prose", "general")])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/documents/facets")).json()

    assert body["kinds"] == {"book": 1}


@pytest.mark.anyio
async def test_facets_is_not_read_as_a_document_id(test_db):
    """`/documents/{id}` is declared after this route; order is what makes it work."""
    _, factory = test_db
    await _seed(factory, [("pdf", "prose", "general")])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/documents/facets")
    assert r.status_code == 200
    assert "kinds" in r.json()


@pytest.mark.anyio
async def test_an_empty_library_reports_nothing_rather_than_failing(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/documents/facets")).json()
    assert body == {"kinds": {}, "formats": {}, "total": 0, "favorite_count": 0}
