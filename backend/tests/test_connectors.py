"""Connectors as separate processes (#435): install from a folder, claim a link, fetch, ingest."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import DocumentModel
from app.services import connectors
from app.services.connector_runner import ConnectorFailed, ConnectorTimeout, call
from app.services.ingestion_jobs import get_ingestion_jobs
from app.services.parser import DocumentParser
from tests.connector_fixture import SDK, install, write_fixture

SECRET = "fixture-token-5f2c"


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    root = tmp_path_factory.mktemp("connectors")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(connectors, "connectors_root", lambda: root)
        yield install(tmp_path_factory, root, "fixture-source", "FixtureSource")


def test_install_records_what_the_connector_describes(installed):
    assert installed.name == "fixture-source"
    assert installed.description["terms"]["url"] == "https://fixture.example/terms"
    record = json.loads(
        (connectors.connectors_root() / "fixture-source" / "connector.json").read_text()
    )
    assert record["entry"] == "fixture_source:FixtureSource"
    assert connectors.connector_for_url("https://fixture.example/book").name == "fixture-source"
    assert connectors.connector_for_url("https://elsewhere.example/fixture.example/") is None


def test_a_folder_must_declare_exactly_one_connector(tmp_path):
    folder = write_fixture(tmp_path / "src", entry_points="")
    with pytest.raises(connectors.ConnectorInstallFailed, match="declares 0"):
        asyncio.run(connectors.install_from_folder(folder))


@pytest.mark.parametrize(
    ("description", "message"),
    [
        ({"name": "other"}, "describe names the connector 'other'"),
        (
            {"name": "x", "terms": {"statement": "s", "url": "http://x"}},
            "does not state its source",
        ),
        (
            {
                "name": "x",
                "terms": {"statement": "s", "url": "https://x/t"},
                "url_prefixes": [".*"],
            },
            "which is not a URL prefix",
        ),
        (
            {"name": "x", "terms": {"statement": "s", "url": "https://x/t"}, "media": ["video"]},
            "x writes 'video'",
        ),
        (
            {"name": "x", "terms": {"statement": "s", "url": "https://x/t"}, "tools": ["curl"]},
            "x runs 'curl'",
        ),
    ],
)
def test_a_description_is_checked_before_it_is_recorded(description, message):
    with pytest.raises(connectors.ConnectorInstallFailed, match=message):
        connectors._check_description("x", description)


async def test_credentials_reach_the_connector_only_in_its_request(installed, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-backend-secret")
    connectors.save_credentials("fixture-source", {"token": SECRET})
    seen = await call(
        installed, "preview", credentials=connectors.load_credentials("fixture-source")
    )
    assert seen["token"] == SECRET
    assert SECRET not in json.dumps(seen["argv"])
    assert SECRET not in json.dumps(seen["env"])
    assert "OPENAI_API_KEY" not in seen["env"]
    if sys.platform != "win32":
        stored = connectors.connectors_root() / "fixture-source" / "credentials.json"
        assert stored.stat().st_mode & 0o777 == 0o600


async def _ingest_link(url: str, monkeypatch, installed) -> tuple[str, AsyncMock]:
    ingested = AsyncMock()
    monkeypatch.setattr("app.workflows.connector_ingestion.run_ingestion", ingested)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/documents/ingest-url", json={"url": url})
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["document_id"]
    await get_ingestion_jobs().get(doc_id)
    return doc_id, ingested


async def test_a_claimed_link_is_fetched_stored_and_ingested(installed, test_db, monkeypatch):
    _, factory, tmp_path = test_db
    doc_id, ingested = await _ingest_link("https://fixture.example/book", monkeypatch, installed)

    stored = tmp_path / "raw" / f"{doc_id}.bundle"
    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
    assert (doc.title, doc.source_url, doc.file_path) == (
        "Fixture Systems",
        "https://fixture.example/book",
        str(stored),
    )
    ingested.assert_awaited_once_with(doc_id, str(stored), "md")
    sections = DocumentParser().parse(stored, doc.format).sections
    assert [s.heading for s in sections] == ["Storage", "Replication"]
    assert sorted(p.name for p in (tmp_path / "raw").iterdir()) == [stored.name]


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("crash", "fixture-source: fixture-source exited with code 3 before answering"),
        ("auth", "fixture-source: Sign in to Fixture again."),
    ],
)
async def test_a_failed_fetch_marks_the_document_and_stores_nothing(
    installed, test_db, monkeypatch, kind, message
):
    _, factory, tmp_path = test_db
    doc_id, ingested = await _ingest_link(f"https://fixture.example/{kind}", monkeypatch, installed)

    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
    assert doc.stage == "error"
    assert doc.error_message.startswith(message)
    ingested.assert_not_called()
    assert list((tmp_path / "raw").iterdir()) == []


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie still answers kill(0); it has exited, so it counts as stopped.
    try:
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True


@pytest.mark.skipif(
    sys.platform == "win32", reason="process groups are POSIX; Windows uses taskkill"
)
async def test_a_timeout_stops_the_connector_and_what_it_started(installed, tmp_path):
    dest = tmp_path / "fetch"
    with pytest.raises(ConnectorTimeout, match="did not answer within 3s"):
        await call(
            installed, "fetch", input={"url": "https://fixture.example/hang"}, dest=str(dest),
            timeout_s=3,
        )  # fmt: skip
    connector_pid, child_pid = map(int, (dest / "pids").read_text().split())
    await asyncio.sleep(0.5)
    assert not _alive(connector_pid)
    assert not _alive(child_pid)


async def test_an_unanswered_request_is_a_failure_not_a_hang(installed, tmp_path):
    broken = installed.__class__(
        name="fixture-source", python=installed.python, entry="fixture_source:Missing",
        description=installed.description,
    )  # fmt: skip
    with pytest.raises(ConnectorFailed, match="AttributeError"):
        await call(broken, "describe")


async def test_a_connector_document_is_reimported_from_its_bundle(installed, test_db, monkeypatch):
    doc_id, _ = await _ingest_link("https://fixture.example/book", monkeypatch, installed)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/documents/{doc_id}/reparse", json={"confirm": False})
    # Markdown with a URL, but its own stored source: never re-fetched as a web article.
    assert resp.json()["source"] == "file"


# --- the SDK itself ---------------------------------------------------------------------------


def test_the_sdk_imports_only_the_standard_library():
    """Never `app`, and never a package: an AGPL dependency would reach every connector."""
    own = {"luminary_source_sdk"}
    for path in (SDK / "src" / "luminary_source_sdk").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                roots = [(node.module or "").split(".")[0]]
            else:
                continue
            for root in roots:
                assert root in own or root in sys.stdlib_module_names, f"{path.name} imports {root}"
    pyproject = (SDK / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in pyproject


def test_the_sdk_declares_what_the_core_accepts(sdk):
    assert (sdk.protocol.MEDIA, sdk.protocol.TOOLS) == (connectors.MEDIA, connectors.TOOLS)


@pytest.fixture
def sdk(monkeypatch):
    monkeypatch.syspath_prepend(str(SDK / "src"))
    import luminary_source_sdk

    return luminary_source_sdk


def test_what_the_sdk_writes_the_core_stores(sdk, tmp_path):
    from app.services.source_bundle import store_bundle

    writer = sdk.BundleWriter(tmp_path / "out")
    writer.add_section("one", "Storage", markdown="A log is an append-only sequence of records.")
    cover = writer.add_asset("cover.jpg", b"\xff\xd8cover")
    writer.finish(
        connector=("fixture", "0.1.0"),
        title="Fixture Systems",
        terms=sdk.Terms("Fixture pages may be downloaded.", "https://fixture.example/terms"),
        cover=cover,
    )
    manifest = store_bundle(tmp_path / "out", tmp_path / "raw" / "doc.bundle")
    assert (manifest.title, manifest.cover, manifest.sections[0].file) == (
        "Fixture Systems",
        "assets/cover.jpg",
        "sections/one.md",
    )


def test_the_sdk_refuses_a_path_that_leaves_the_bundle(sdk, tmp_path):
    writer = sdk.BundleWriter(tmp_path / "out")
    with pytest.raises(sdk.BundleError, match="not a safe path"):
        writer.add_asset("../outside.png", b"x")
