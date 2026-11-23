"""A phone revalidates a document's sections instead of downloading them again (#452).

The ETag is the hash of the exact body: unchanged text answers 304 with no body, and any change
to a section's text changes the tag.
"""

import gzip

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app.main import app
from app.models import SectionModel
from tests.factories import make_document, make_section

DOC = "doc-cache"
BODY = "A log is an append-only sequence of records. " * 60


@pytest.fixture
async def client(memory_db):
    async with memory_db.factory() as session:
        session.add(make_document(id=DOC))
        session.add_all(
            [
                make_section(id="s1", document_id=DOC, section_order=0, body=BODY),
                make_section(id="s2", document_id=DOC, section_order=1, body="Short."),
            ]
        )
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        yield c


@pytest.mark.parametrize("path", [f"/sections/{DOC}/content", f"/sections/{DOC}/content/s1"])
async def test_an_unchanged_section_answers_304_and_a_changed_one_a_new_tag(
    client, memory_db, path
):
    first = await client.get(path)
    assert first.status_code == 200
    tag = first.headers["etag"]

    again = await client.get(path, headers={"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b""
    weak = await client.get(path, headers={"If-None-Match": f'W/{tag}, "other"'})
    assert weak.status_code == 304

    async with memory_db.factory() as session:
        await session.execute(
            update(SectionModel).where(SectionModel.id == "s1").values(body="New.")
        )
        await session.commit()
    changed = await client.get(path, headers={"If-None-Match": tag})
    assert changed.status_code == 200 and changed.headers["etag"] != tag


async def test_a_large_page_is_compressed_only_for_a_client_that_accepts_it(client):
    path = f"/sections/{DOC}/content"
    plain = await client.get(path, headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers
    raw = await client.get(path, headers={"Accept-Encoding": "gzip"})
    assert raw.headers["content-encoding"] == "gzip"
    assert raw.json() == plain.json()
    assert len(gzip.compress(plain.content)) < len(plain.content) / 4
    assert raw.headers["etag"] == plain.headers["etag"]


async def test_a_small_body_is_sent_as_it_is(client):
    resp = await client.get(f"/sections/{DOC}/content/s2", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200 and "content-encoding" not in resp.headers
    assert resp.json()["content"] == "Short."
