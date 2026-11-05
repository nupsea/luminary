"""A YouTube or O'Reilly link that no installed connector claims names what to install (#467),
and is never read as a web article (#430)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import DocumentModel


@pytest.fixture
def no_connectors(monkeypatch, tmp_path):
    from app.services import connectors

    monkeypatch.setattr(connectors, "connectors_root", lambda: tmp_path / "connectors")


@pytest.fixture
def article_reads(monkeypatch):
    """Records every link the web-article path is asked to read, and reads none."""
    asked: list[str] = []

    async def _fetch(url):
        asked.append(url)
        raise RuntimeError("stop before the network")

    monkeypatch.setattr("app.routers.documents.fetch_remote_document", _fetch)
    return asked


async def _post(url: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/documents/ingest-url", json={"url": url})


@pytest.mark.parametrize(
    ("url", "connector", "catalogue", "instead"),
    [
        ("https://www.youtube.com/watch?v=t1", "youtube", True, "audio or video file"),
        ("https://youtu.be/t1", "youtube", True, "audio or video file"),
        ("https://m.youtube.com/watch?v=t1", "youtube", True, "audio or video file"),
        ("https://learning.oreilly.com/library/view/x/9781098100001/", "oreilly", False, "EPUB"),
        ("https://www.oreilly.com/library/view/x/1/ch01.html", "oreilly", False, "EPUB"),
    ],
)
async def test_an_unclaimed_link_names_the_connector_to_install(
    test_db, no_connectors, article_reads, url, connector, catalogue, instead
):
    _, factory, _ = test_db
    resp = await _post(url)

    assert resp.status_code == 422
    body = resp.json()
    assert (body["connector"], body["catalogue"]) == (connector, catalogue)
    assert instead in body["detail"]
    assert ("Settings" in body["detail"]) is catalogue
    assert article_reads == [], "a known source's link was read as a web article"
    async with factory() as session:
        assert (await session.scalars(select(DocumentModel))).all() == []


async def test_an_oreilly_article_is_still_a_web_page(test_db, no_connectors, article_reads):
    """oreilly.com's own articles are not books; only /library/ links need the connector."""
    url = "https://www.oreilly.com/radar/some-article/"
    with pytest.raises(RuntimeError, match="stop before the network"):
        await _post(url)
    assert article_reads == [url]
