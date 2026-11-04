"""Installing a connector from the catalogue (#437): uv fetched on request, the archive pinned by
sha256, exactly its uv.lock installed, and an uninstall that leaves its documents readable."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import (
    component_download,
    components,
    connector_catalogue,
    connectors,
    managed_tools,
)
from app.services.component_download import extract_prefix
from app.services.connector_catalogue import CatalogueEntry
from app.services.ingestion_jobs import get_ingestion_jobs
from app.services.parser import DocumentParser
from tests.connector_fixture import SECRET, entry, write_fixture

TERMS = "Fixture pages may be downloaded for personal study."
TOP = "fixture-repo-abc123/books/"


def _tar_gz(members: dict[str, bytes], mode: int = 0o644) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as bundle:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            bundle.addfile(info, io.BytesIO(data))
    return raw.getvalue()


@pytest.fixture
def served(monkeypatch):
    """The downloader's client answers from `bodies`, by URL."""
    bodies: dict[str, bytes] = {}
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        body = bodies.get(str(request.url))
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, content=body, headers={"Content-Length": str(len(body))})

    def make(**kwargs):
        kwargs.pop("transport", None)
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(component_download.httpx, "AsyncClient", make)
    return bodies


@pytest.fixture(scope="module")
def connector_archive(tmp_path_factory) -> bytes:
    """The fixture connector's folder, locked, as a repository archive holds it."""
    if components.resolve_tool("uv") is None:
        pytest.skip("locking the fixture connector needs uv")
    folder = write_fixture(
        tmp_path_factory.mktemp("repo") / "books",
        entry_points=entry("fixture-source", "FixtureSource"),
    )
    subprocess.run([components.resolve_tool("uv"), "lock", "--project", str(folder)], check=True,
                   capture_output=True)  # fmt: skip
    files = {f"{TOP}{p.relative_to(folder).as_posix()}": p.read_bytes()
             for p in sorted(folder.rglob("*")) if p.is_file()}  # fmt: skip
    return _tar_gz(files)


@pytest.fixture
def catalogue_of(monkeypatch, tmp_path, served):
    """Point `connectors_root` at a fresh folder and the catalogue at one fixture entry."""
    root = tmp_path / "connectors"
    monkeypatch.setattr(connectors, "connectors_root", lambda: root)

    def _offer(body: bytes, *, sha256: str | None = None, statement: str = TERMS) -> CatalogueEntry:
        url = "https://catalogue.example/fixture-repo.tar.gz"
        served[url] = body
        item = CatalogueEntry(
            name="fixture-source", label="Fixture Books", version="0.1.0",
            summary="Fixture books.", licence="Apache-2.0", terms_statement=statement,
            terms_url="https://fixture.example/terms", repository="https://example.com/repo",
            archive_url=url, sha256=sha256 or hashlib.sha256(body).hexdigest(),
            size_bytes=len(body), member_prefix=TOP,
        )  # fmt: skip
        monkeypatch.setattr(connector_catalogue, "catalogue_entries", lambda: (item,))
        return item

    return _offer


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _install(client: AsyncClient, name: str = "fixture-source") -> list[dict]:
    resp = await client.post(f"/connectors/catalogue/{name}/install")
    assert resp.status_code == 200
    return [json.loads(line[5:]) for line in resp.text.splitlines() if line.startswith("data:")]


async def test_the_catalogue_shows_licence_and_terms_before_an_install(
    catalogue_of, connector_archive
):
    catalogue_of(connector_archive)
    async with _client() as client:
        (item,) = (await client.get("/connectors/catalogue")).json()["connectors"]
    assert (item["licence"], item["terms"]) == (
        "Apache-2.0", {"statement": TERMS, "url": "https://fixture.example/terms"},
    )  # fmt: skip
    assert item["installed_version"] is None


async def test_a_catalogue_connector_installs_ingests_and_uninstalls(
    catalogue_of, connector_archive, test_db, monkeypatch
):
    _, factory, tmp_path = test_db
    catalogue_of(connector_archive)
    monkeypatch.setattr("app.workflows.connector_ingestion.run_ingestion", AsyncMock())
    async with _client() as client:
        events = await _install(client)
        listed = (await client.get("/connectors")).json()["connectors"]
        shown = (await client.get("/connectors/catalogue")).json()["connectors"][0]
        connectors.save_credentials("fixture-source", {"token": SECRET})
        resp = await client.post(
            "/documents/ingest-url", json={"url": "https://fixture.example/book"}
        )
        doc_id = resp.json()["document_id"]
        await get_ingestion_jobs().get(doc_id)
        gone = await client.delete("/connectors/fixture-source")
        after = (await client.get("/connectors")).json()["connectors"]
        reimport = await client.post(f"/documents/{doc_id}/reparse", json={"confirm": False})

    assert events[-1] == {"state": "ready", "detail": "Fixture Books 0.1.0 installed"}, events
    assert [c["name"] for c in listed] == ["fixture-source"]
    assert shown["installed_version"] == "0.1.0"
    assert (gone.status_code, after) == (204, [])
    home = connectors.connectors_root() / "fixture-source"
    assert not (home / "env").exists() and not (home / "source").exists()
    # Its documents stay: the core holds their bundles, and re-import reads them offline.
    stored = tmp_path / "raw" / f"{doc_id}.bundle"
    assert [s.heading for s in DocumentParser().parse(stored, "epub").sections] == [
        "Storage", "Replication",
    ]  # fmt: skip
    assert reimport.json()["source"] == "file"


async def test_a_tampered_archive_is_refused_before_anything_installs(
    catalogue_of, connector_archive
):
    catalogue_of(connector_archive, sha256=hashlib.sha256(b"what was reviewed").hexdigest())
    async with _client() as client:
        events = await _install(client)
        listed = (await client.get("/connectors")).json()["connectors"]
    assert events[-1]["state"] == "failed"
    assert "checksum" in events[-1]["detail"]
    assert listed == []
    assert not (connectors.connectors_root() / "fixture-source" / "source").exists()


async def test_an_archive_whose_lock_is_stale_is_refused(catalogue_of, connector_archive):
    """Exactly the reviewed lock or nothing: a project that no longer matches its uv.lock would
    otherwise resolve fresh versions at install time."""
    with tarfile.open(fileobj=io.BytesIO(connector_archive), mode="r:gz") as bundle:
        files = {m.name: bundle.extractfile(m).read() for m in bundle if m.isfile()}
    pyproject = f"{TOP}pyproject.toml"
    # A requirement the lock still satisfies (`>=0.1`) is not stale to uv; this one is.
    files[pyproject] = files[pyproject].replace(
        b'requires-python = ">=3.11"', b'requires-python = ">=3.12"'
    )
    catalogue_of(_tar_gz(files))
    async with _client() as client:
        events = await _install(client)
        listed = (await client.get("/connectors")).json()["connectors"]
    assert events[-1]["state"] == "failed"
    assert events[-1]["detail"].startswith("uv sync failed"), events[-1]
    assert listed == []


async def test_a_connector_unlike_its_entry_is_removed_again(catalogue_of, connector_archive):
    """The user agreed to the terms the entry showed; a connector stating others is not kept."""
    catalogue_of(connector_archive, statement="Something gentler than the source says.")
    async with _client() as client:
        events = await _install(client)
        listed = (await client.get("/connectors")).json()["connectors"]
    assert events[-1] == {
        "state": "failed",
        "detail": "Fixture Books from the catalogue does not describe itself as its entry does",
    }
    assert listed == []


async def test_without_uv_the_installer_is_fetched_first(
    catalogue_of, connector_archive, monkeypatch
):
    catalogue_of(connector_archive)
    asked: list[str] = []

    async def _install_component(component_id):
        asked.append(component_id)
        yield {"state": "failed", "detail": "no network"}

    monkeypatch.setattr(connector_catalogue, "resolve_tool", lambda name: None)
    monkeypatch.setattr(connector_catalogue, "install_component", _install_component)
    async with _client() as client:
        events = await _install(client)
    assert asked == ["uv"]
    assert events[-1] == {
        "state": "failed",
        "detail": "Could not fetch the connector installer: no network",
    }


@pytest.mark.parametrize(
    ("platform", "machine", "asset", "prefix"),
    [
        ("darwin", "arm64", "uv-aarch64-apple-darwin.tar.gz", "uv-aarch64-apple-darwin/"),
        ("linux", "x86_64", "uv-x86_64-unknown-linux-gnu.tar.gz", "uv-x86_64-unknown-linux-gnu/"),
        ("win32", "AMD64", "uv-x86_64-pc-windows-msvc.zip", ""),
    ],
)
def test_uv_comes_from_its_own_release_pinned_for_each_host(
    monkeypatch, platform, machine, asset, prefix
):
    import platform as platform_module

    monkeypatch.setattr(managed_tools.sys, "platform", platform)
    monkeypatch.setattr(platform_module, "machine", lambda: machine)
    source = managed_tools.uv_source()
    assert source["url"] == (
        f"https://github.com/astral-sh/uv/releases/download/{managed_tools.UV_VERSION}/{asset}"
    )
    assert (source["asset"], source["member_prefix"], len(source["sha256"])) == (asset, prefix, 64)


async def test_the_fetched_uv_is_the_one_resolved(monkeypatch, tmp_path, served):
    binary = b"#!/bin/sh\necho uv\n"
    body = _tar_gz({"uv-aarch64-apple-darwin/uv": binary}, mode=0o755)
    url = "https://uv.example/uv-aarch64-apple-darwin.tar.gz"
    served[url] = body
    monkeypatch.setattr(managed_tools, "machine_root", lambda: tmp_path)
    monkeypatch.setattr(managed_tools, "uv_source", lambda: {
        "url": url, "asset": "uv-aarch64-apple-darwin.tar.gz", "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(), "member_prefix": "uv-aarch64-apple-darwin/",
    })  # fmt: skip
    comp = next(c for c in components.catalogue() if c.id == "uv")

    events = [e async for e in managed_tools.install(comp.ref, comp.label)]

    assert events[-1]["state"] == "ready", events
    installed = tmp_path / "tools" / "uv" / "uv"
    assert installed.read_bytes() == binary
    assert components.resolve_tool("uv") == str(installed)
    if components.sys.platform != "win32":
        assert installed.stat().st_mode & 0o111, "uv must stay executable"


def test_a_gzip_tar_unpacks_under_its_prefix_and_nothing_else(tmp_path):
    archive = tmp_path / "a.tar.gz"
    archive.write_bytes(_tar_gz({"top/keep/a.txt": b"a", "top/other.txt": b"o"}))
    assert extract_prefix(archive, "top/keep/", tmp_path / "out") == 1
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["a.txt"]


def test_entries_pin_an_archive_and_state_terms(monkeypatch):
    """Every shipped entry names an archive by full sha256 and a folder inside it, and quotes
    terms with a link: the review checklist's minimum (#438)."""
    for item in connector_catalogue._ENTRIES:
        assert len(item.sha256) == 64 and int(item.sha256, 16) >= 0
        assert item.archive_url.startswith("https://") and item.member_prefix.endswith("/")
        assert item.terms_statement and item.terms_url.startswith("https://")
        assert item.size_bytes > 0
