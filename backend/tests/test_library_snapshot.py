"""A library's snapshot restores into a new root that answers as the original does (#390)."""

import asyncio
import io
import json
import re
import tarfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

import app.services.devices as devices
from app.database import get_session_factory
from app.db_init import open_library
from app.exceptions import Conflict, InvalidInput
from app.library import use_library
from app.main import app
from app.models import DeviceModel, DocumentModel, SettingsModel
from app.services import library_snapshot
from app.services.library_snapshot import restore_snapshot, take_snapshot
from app.services.vector_store import get_lancedb_service
from app.storage import LIBRARY_FILE_DIRS, library_root
from tests.factories import make_document
from tests.test_e2e_upload import FIXTURES_DIR, upload_db  # noqa: F401
from tests.test_library_binding import _pair_into
from tests.test_library_context import _CHUNK, DOC, _close, two_libraries  # noqa: F401

APP = "http://127.0.0.1:7820"


def _head() -> str:
    from alembic.script import ScriptDirectory

    from app.db_init import _alembic_config

    return ScriptDirectory.from_config(_alembic_config(None)).get_current_head()


async def _ingest(client: AsyncClient) -> str:
    with (FIXTURES_DIR / "art_of_unix_ch1.txt").open("rb") as fh:
        resp = await client.post(
            "/documents/ingest", files={"file": ("art_of_unix_ch1.txt", fh, "text/plain")}
        )
    doc_id = resp.json()["document_id"]
    for _ in range(1000):
        await asyncio.sleep(0.05)
        if (await client.get(f"/documents/{doc_id}/status")).json()["done"]:
            return doc_id
    pytest.fail("ingestion did not finish")


async def _answers(client: AsyncClient, doc_id: str, headers: dict[str, str]) -> dict:
    documents = (await client.get("/documents", headers=headers)).json()["items"]
    hits = (await client.get("/search", params={"q": "unix philosophy"}, headers=headers)).json()
    cards = (await client.get(f"/flashcards/{doc_id}", headers=headers)).json()
    return {
        "documents": sorted((d["id"], d["title"]) for d in documents),
        "search": sorted(
            (m["global_rank"], m["chunk_id"]) for g in hits["results"] for m in g["matches"]
        ),
        "cards": sorted((c["question"], c["answer"]) for c in cards),
    }


@pytest.mark.integration_http
async def test_a_restored_library_answers_as_the_original(upload_db, tmp_path):  # noqa: F811
    devices._active_code = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url=APP) as client:
        doc_id = await _ingest(client)
        card = await client.post(
            "/flashcards/create-trace",
            json={
                "document_id": doc_id,
                "question": "Who wrote the Unix philosophy?",
                "answer": "Doug McIlroy.",
                "source_excerpt": "Doug McIlroy, the inventor of Unix pipes",
            },
        )
        assert card.status_code == 201, card.text
        async with get_session_factory()() as session:
            # The fixture's schema comes from create_all; a real library is stamped.
            await session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
            await session.execute(
                text("INSERT INTO alembic_version VALUES (:head)"), {"head": _head()}
            )
            session.add(SettingsModel(key="openai_api_key", value="__plain__:sk-not-a-key"))
            session.add(SettingsModel(key="llm_mode", value="private"))
            session.add(DeviceModel(id="d-1", name="laptop", token_hash="0" * 64))
            await session.commit()

        archive = tmp_path / "library.tar.gz"
        manifest = await take_snapshot(archive)
        await restore_snapshot(archive, "restored")
        device = await _pair_into(client, "restored")
        try:
            original = await _answers(client, doc_id, {})
            restored = await _answers(client, doc_id, device)
            with use_library("restored"):
                async with get_session_factory()() as session:
                    settings = {
                        row.key: row.value
                        for row in (await session.execute(select(SettingsModel))).scalars()
                    }
                    registry = (await session.execute(select(DeviceModel))).scalars().all()
        finally:
            devices._active_code = None
            await _close("restored")

    assert original["documents"] == [(doc_id, "art_of_unix_ch1")]
    assert original["search"] and original["cards"]
    assert restored == original
    assert "openai_api_key" not in settings and settings["llm_mode"] == "private"
    assert registry == []
    assert manifest.embedder == library_snapshot.EMBEDDER
    assert manifest.vector_versions


# -- refusals ----------------------------------------------------------------------------------


@pytest.fixture
async def source(two_libraries):  # noqa: F811
    """A small library, `first`, and its snapshot."""
    await open_library("first")
    with use_library("first"):
        async with get_session_factory()() as session:
            session.add(make_document(id=DOC, title="The Odyssey"))
            await session.commit()
        await asyncio.to_thread(
            get_lancedb_service().upsert_chunks, [{**_CHUNK, "document_id": DOC}]
        )
        (library_root() / "raw").mkdir()
        (library_root() / "raw" / f"{DOC}.txt").write_text("Sing to me of the man, Muse.")
        archive = two_libraries / "first.tar.gz"
        await take_snapshot(archive)
    yield archive
    await _close("first", "second")


def _rewrite(archive: Path, edit) -> Path:
    """A copy of *archive* with each member passed through *edit*(info, data) -> (info, data)."""
    out = archive.with_name("edited.tar.gz")
    with tarfile.open(archive, "r:gz") as src, tarfile.open(out, "w:gz") as dst:
        for info in src.getmembers():
            data = src.extractfile(info).read() if info.isfile() else b""
            info, data = edit(info, data)
            info.size = len(data)
            dst.addfile(info, io.BytesIO(data))
    return out


def _manifest_edit(**changes):
    def edit(info, data):
        if info.name == library_snapshot.MANIFEST:
            data = json.dumps({**json.loads(data), **changes}).encode()
        return info, data

    return edit


async def test_a_restore_has_all_the_originals_rows_files_and_vectors(source):
    await restore_snapshot(source, "second")
    with use_library("second"):
        root = library_root()
        await open_library("second")
        async with get_session_factory()() as session:
            titles = (await session.execute(select(DocumentModel.title))).scalars()
            assert list(titles) == ["The Odyssey"]
        assert get_lancedb_service().count_for_document(DOC) == 1
    assert (root / "raw" / f"{DOC}.txt").read_text() == "Sing to me of the man, Muse."


async def test_a_restore_never_writes_into_the_default_or_a_used_library(source):
    with pytest.raises(InvalidInput):
        await restore_snapshot(source, "default")
    await restore_snapshot(source, "second")
    with pytest.raises(Conflict):
        await restore_snapshot(source, "second")


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (_manifest_edit(schema_revision="ffffffffffff"), "newer version"),
        (_manifest_edit(embedder={"model": "BAAI/bge-m3", "dim": 1024}), "embedder"),
        (_manifest_edit(format=2), "format"),
        (
            lambda info, data: (
                info,
                b"Sing to me of the woman, Muse." if info.name.endswith(".txt") else data,
            ),
            "damaged",
        ),
    ],
)
async def test_a_snapshot_that_cannot_be_trusted_restores_nothing(source, edit, message):
    with pytest.raises(InvalidInput, match=message):
        await restore_snapshot(_rewrite(source, edit), "second")
    assert not library_root(library="second").exists()


async def test_a_member_outside_the_root_restores_nothing(source):
    def escape(info, data):
        if info.name.endswith(".txt"):
            info.name = "../escaped.txt"
        return info, data

    with pytest.raises(InvalidInput, match="unsafe"):
        await restore_snapshot(_rewrite(source, escape), "second")
    assert not library_root(library="second").exists()
    assert not list(source.parent.rglob("escaped.txt"))


async def test_no_snapshot_while_a_document_is_ingesting(two_libraries):  # noqa: F811
    await open_library("first")
    try:
        with use_library("first"):
            async with get_session_factory()() as session:
                session.add(make_document(id=DOC, stage="chunking"))
                await session.commit()
            with pytest.raises(Conflict, match="ingested"):
                await take_snapshot(two_libraries / "first.tar.gz")
    finally:
        await _close("first")
    assert not (two_libraries / "first.tar.gz").exists()


async def test_a_vector_written_after_the_versions_were_read_is_not_restored(two_libraries):  # noqa: F811
    await open_library("first")
    try:
        with use_library("first"):
            vectors = get_lancedb_service()
            await asyncio.to_thread(vectors.upsert_chunks, [{**_CHUNK, "document_id": DOC}])
            versions = await asyncio.to_thread(vectors.table_versions)
            later = {**_CHUNK, "chunk_id": "c-2", "document_id": DOC}
            await asyncio.to_thread(vectors.upsert_chunks, [later])
            await asyncio.to_thread(vectors.pin_versions, versions)
            assert vectors.count_for_document(DOC) == 1
    finally:
        await _close("first")


def test_a_snapshot_carries_every_folder_the_app_keeps_in_a_library_root():
    app_dir = Path(__file__).parent.parent / "app"
    joined = {
        name
        for path in app_dir.rglob("*.py")
        for name in re.findall(
            r'library_root\([^)]*\)\s*/\s*"([^"]+)"', path.read_text(encoding="utf-8")
        )
    }
    carried = {library_snapshot.DATABASE, library_snapshot.VECTORS, *LIBRARY_FILE_DIRS}
    assert joined, "the pattern no longer finds library_root joins"
    assert joined <= carried, f"not in a snapshot: {sorted(joined - carried)}"


async def test_a_vector_written_while_the_snapshot_ran_is_not_restored(two_libraries, monkeypatch):  # noqa: F811
    from app.services.vector_store import LanceDBService

    await open_library("first")
    try:
        with use_library("first"):
            vectors = get_lancedb_service()
            await asyncio.to_thread(vectors.upsert_chunks, [{**_CHUNK, "document_id": DOC}])
            before = await asyncio.to_thread(vectors.table_versions)
            # Lands after the versions are read and before the files are copied.
            later = {**_CHUNK, "chunk_id": "c-2", "document_id": DOC}
            await asyncio.to_thread(vectors.upsert_chunks, [later])
            monkeypatch.setattr(LanceDBService, "table_versions", lambda _self: before)
            await take_snapshot(two_libraries / "first.tar.gz")
            assert vectors.count_for_document(DOC) == 2
        await restore_snapshot(two_libraries / "first.tar.gz", "second")
        with use_library("second"):
            assert get_lancedb_service().count_for_document(DOC) == 1
    finally:
        await _close("first", "second")
