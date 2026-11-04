"""`/connectors`: what the settings card, the connect form and the upload dialog read and send,
drawn from the connector's own description (#436)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import DocumentModel
from app.services import connectors
from app.services.ingestion_jobs import get_ingestion_jobs
from app.services.parser import DocumentParser
from tests.connector_fixture import SECRET, install

BOOK = "https://fixture.example/book"


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    root = tmp_path_factory.mktemp("connectors")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(connectors, "connectors_root", lambda: root)
        install(tmp_path_factory, root, "fixture-source", "FixtureSource")
        yield root


@pytest.fixture
def signed_out(root):
    connectors.delete_credentials("fixture-source")
    yield
    connectors.delete_credentials("fixture-source")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _documents(factory) -> list[DocumentModel]:
    async with factory() as session:
        return list((await session.scalars(select(DocumentModel))).all())


async def test_the_list_is_what_the_connector_described(signed_out):
    async with _client() as client:
        (item,) = (await client.get("/connectors")).json()["connectors"]
    assert (item["name"], item["label"], item["preview"], item["connected"]) == (
        "fixture-source", "Fixture Books", True, False,
    )  # fmt: skip
    assert item["url_prefixes"] == ["https://fixture.example/"]
    assert item["credentials"][0] | {} == {
        "name": "token", "label": "Access token", "secret": True, "required": True,
        "help": "From your account", "multiline": False,
    }  # fmt: skip
    assert [f["name"] for f in item["inputs"]] == ["edition"]
    assert item["terms"]["url"] == "https://fixture.example/terms"


async def test_connect_checks_with_the_connector_before_storing(signed_out):
    async with _client() as client:
        refused = await client.put(
            "/connectors/fixture-source/credentials", json={"values": {"token": "wrong"}}
        )
        assert connectors.load_credentials("fixture-source") == {}
        ok = await client.put(
            "/connectors/fixture-source/credentials", json={"values": {"token": SECRET}}
        )
        status = (await client.get("/connectors/fixture-source/status")).json()
        listed = (await client.get("/connectors")).json()["connectors"][0]["connected"]
        gone = await client.delete("/connectors/fixture-source/credentials")
        after = (await client.get("/connectors/fixture-source/status")).json()

    assert refused.status_code == 401
    assert refused.json()["detail"] == "Fixture Books: that token was refused"
    assert (ok.status_code, ok.json()["account"]) == (200, "reader@fixture.example")
    assert status == {"connected": True, "valid": True, "account": "reader@fixture.example",
                      "error": None}  # fmt: skip
    assert listed is True
    assert (gone.status_code, after["connected"]) == (204, False)
    assert connectors.load_credentials("fixture-source") == {}


async def test_a_field_the_connector_does_not_declare_is_refused(signed_out):
    async with _client() as client:
        resp = await client.put(
            "/connectors/fixture-source/credentials", json={"values": {"password": "x"}}
        )
    assert resp.status_code == 422


@pytest.mark.parametrize("route", ["/connectors/fixture-source/ingest", "/documents/ingest-url"])
async def test_a_link_needing_a_sign_in_opens_the_connect_form_before_any_document(
    signed_out, test_db, route
):
    _, factory, _ = test_db
    async with _client() as client:
        resp = await client.post(route, json={"url": BOOK})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Connect Fixture Books first.", "connector": "fixture-source"}
    assert await _documents(factory) == []


async def test_the_preview_choice_decides_what_is_fetched(root, test_db, monkeypatch):
    _, factory, tmp_path = test_db
    connectors.save_credentials("fixture-source", {"token": SECRET})
    ingested = AsyncMock()
    monkeypatch.setattr("app.workflows.connector_ingestion.run_ingestion", ingested)
    async with _client() as client:
        preview = await client.post("/connectors/fixture-source/preview", json={"url": BOOK})
        resp = await client.post(
            "/connectors/fixture-source/ingest", json={"url": BOOK, "input": {"parts": ["two"]}}
        )
        await get_ingestion_jobs().get(resp.json()["document_id"])

    assert preview.status_code == 200, preview.text
    (choice,) = preview.json()["choices"]
    assert (preview.json()["title"], choice["field"], choice["default"]) == (
        "Fixture Systems", "parts", ["one", "two"],
    )  # fmt: skip
    assert [o["label"] for o in choice["options"]] == ["Storage", "Replication"]
    stored = tmp_path / "raw" / f"{resp.json()['document_id']}.bundle"
    assert [s.heading for s in DocumentParser().parse(stored, "epub").sections] == ["Replication"]


async def test_a_choice_cannot_replace_the_link_or_the_tools(root, test_db, monkeypatch):
    connectors.save_credentials("fixture-source", {"token": SECRET})
    monkeypatch.setattr("app.workflows.connector_ingestion.run_ingestion", AsyncMock())
    sent = {}

    async def _call(connector, op, **kwargs):
        sent.update(kwargs["input"])
        raise connectors.ConnectorNotInstalled("stop here")

    monkeypatch.setattr("app.workflows.connector_ingestion.call", _call)
    async with _client() as client:
        resp = await client.post(
            "/connectors/fixture-source/ingest",
            json={"url": BOOK, "input": {"url": "https://elsewhere.example/", "tools": {"x": "y"}}},
        )
        await get_ingestion_jobs().get(resp.json()["document_id"])
    assert (sent["url"], sent["tools"]) == (BOOK, {})


@pytest.mark.parametrize(
    ("name", "url", "status"),
    [("fixture-source", "https://elsewhere.example/book", 422), ("missing", BOOK, 404)],
    ids=["unclaimed-link", "unknown-connector"],
)
async def test_a_route_takes_only_its_own_connectors_links(root, name, url, status):
    async with _client() as client:
        resp = await client.post(f"/connectors/{name}/preview", json={"url": url})
    assert resp.status_code == status


async def test_a_declared_input_reaches_the_fetch(root, test_db, monkeypatch):
    """`edition` is a field no first-party connector has: the dialog renders it from the
    description and the value arrives in the connector's input beside the link."""
    import json

    _, _, tmp_path = test_db
    connectors.save_credentials("fixture-source", {"token": SECRET})
    monkeypatch.setattr("app.workflows.connector_ingestion.run_ingestion", AsyncMock())
    async with _client() as client:
        resp = await client.post(
            "/connectors/fixture-source/ingest",
            json={"url": "https://fixture.example/env", "input": {"edition": "2nd"}},
        )
        await get_ingestion_jobs().get(resp.json()["document_id"])
    bundle = tmp_path / "raw" / f"{resp.json()['document_id']}.bundle"
    seen = json.loads((bundle / "sections" / "seen.md").read_text(encoding="utf-8"))
    assert seen["input"]["edition"] == "2nd"
    assert seen["input"]["url"] == "https://fixture.example/env"
