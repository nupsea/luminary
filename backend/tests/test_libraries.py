"""The app works in its active library, and a library moves between machines whole.

Through HTTP: a switch moves the app's reads and writes and nothing else (a paired device
stays in its own library, the device registry stays in the default one); the choice
survives a restart; an export imported on another machine answers as the original.
"""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import app.services.devices as devices
from app.database import get_session_factory
from app.main import app
from app.services import libraries
from app.storage import library_root
from tests.test_library_binding import OWN, _pair_into, _write
from tests.test_library_context import _close
from tests.test_library_snapshot import _head

WORK = "work"
MOVED = "moved"


@pytest.fixture
async def client(memory_db, monkeypatch):
    import app.routers.documents as documents_router

    async def _no_pipeline(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(documents_router, "run_ingestion", _no_pipeline)
    monkeypatch.setenv("HOME", str(memory_db.tmp_path / "home"))
    devices._active_code = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url=OWN) as c:
        yield c
    devices._active_code = None
    libraries._active.clear()
    await _close(WORK, MOVED)


async def _titles(client: AsyncClient, headers: dict[str, str] | None = None) -> list[str]:
    items = (await client.get("/documents", headers=headers or {})).json()["items"]
    return sorted(d["title"] for d in items)


async def _switch(client: AsyncClient, library: str) -> None:
    resp = await client.put("/libraries/active", json={"library": library})
    assert resp.status_code == 200, resp.text
    assert resp.json()["active"] == library


async def test_a_switch_moves_the_apps_reads_and_writes(client):
    await _write(client, {}, "Odyssey")
    created = await client.post("/libraries", json={"library": WORK})
    assert created.status_code == 201, created.text
    assert [lib["id"] for lib in created.json()["libraries"]] == ["default", WORK]
    assert created.json()["active"] == "default"

    await _switch(client, WORK)
    assert await _titles(client) == []
    await _write(client, {}, "Iliad")
    assert await _titles(client) == ["Iliad"]

    await _switch(client, "default")
    assert await _titles(client) == ["Odyssey"]


async def test_a_device_stays_in_its_library_and_the_registry_in_the_default(client):
    device = await _pair_into(client, "default")
    await _write(client, {}, "Odyssey")
    await client.post("/libraries", json={"library": WORK})
    await _switch(client, WORK)

    assert await _titles(client, device) == ["Odyssey"]
    # The app manages devices whichever library it has open.
    listed = (await client.get("/devices")).json()
    assert [d["name"] for d in listed] == ["phone"]
    assert (await client.delete(f"/devices/{listed[0]['id']}")).status_code == 204
    assert (await client.get("/documents", headers=device)).status_code == 401


async def test_a_device_cannot_see_or_switch_libraries(client):
    device = await _pair_into(client, "default")
    assert (await client.get("/libraries", headers=device)).status_code == 403
    resp = await client.put("/libraries/active", json={"library": "default"}, headers=device)
    assert resp.status_code == 403


async def test_the_choice_survives_a_restart_and_a_missing_library_falls_back(client, memory_db):
    await client.post("/libraries", json={"library": WORK})
    await _switch(client, WORK)

    libraries._active.clear()
    assert libraries.active_library() == WORK

    (library_root(library=WORK) / "luminary.db").rename(memory_db.tmp_path / "gone.db")
    libraries._active.clear()
    assert libraries.active_library() == "default"


async def test_names_that_cannot_be_a_library_are_refused(client):
    assert (await client.post("/libraries", json={"library": "../x"})).status_code == 422
    assert (await client.post("/libraries", json={"library": "default"})).status_code == 422
    assert (await client.put("/libraries/active", json={"library": "nowhere"})).status_code == 404
    await client.post("/libraries", json={"library": WORK})
    assert (await client.post("/libraries", json={"library": WORK})).status_code == 409


async def _ready() -> None:
    # The fixture's schema comes from create_all; a real library is stamped. The pipeline is
    # stubbed, so its documents are marked done or a snapshot would wait for them.
    async with get_session_factory()() as session:
        await session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        await session.execute(text("INSERT INTO alembic_version VALUES (:h)"), {"h": _head()})
        await session.execute(text("UPDATE documents SET stage = 'complete'"))
        await session.commit()


async def _export(client: AsyncClient, library: str) -> dict:
    resp = await client.post(f"/libraries/{library}/export")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _import(client: AsyncClient, archive: Path, library: str, **form) -> dict:
    with archive.open("rb") as fh:
        return await client.post(
            "/libraries/import",
            files={"file": (archive.name, fh, "application/gzip")},
            data={"library": library, **form},
        )


async def test_an_exported_library_imports_whole_and_opens(client, memory_db):
    doc = await _write(client, {}, "Odyssey")
    await _ready()
    exported = await _export(client, "default")

    archive = Path(exported["path"])
    folder = memory_db.tmp_path / "home" / libraries.EXPORT_FOLDER
    assert archive.parent == folder
    assert [p.name for p in folder.iterdir()] == [archive.name]  # no partial left behind
    assert exported["contents"] == {"documents": 1, "flashcards": 1, "notes": 1}

    resp = await _import(client, archive, MOVED, activate="true")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["active"] is True
    assert body["source_library"] == "default"
    assert body["contents"] == exported["contents"]
    assert body["files"] == exported["files"]

    assert await _titles(client) == ["Odyssey"]
    assert len((await client.get(f"/flashcards/{doc}")).json()) == 1
    assert (library_root(library=MOVED) / "raw" / f"{doc}.txt").is_file()
    assert not list((memory_db.tmp_path / "downloads").iterdir())


async def test_an_import_that_cannot_be_trusted_leaves_nothing(client, memory_db):
    await _write(client, {}, "Odyssey")
    await _ready()
    archive = Path((await _export(client, "default"))["path"])

    not_a_snapshot = memory_db.tmp_path / "notes.tar.gz"
    not_a_snapshot.write_bytes(b"these are my notes")
    resp = await _import(client, not_a_snapshot, MOVED)
    assert resp.status_code == 422, resp.text
    assert "not a readable library snapshot" in resp.json()["detail"]

    assert (await _import(client, archive, "default")).status_code == 422
    assert (await _import(client, archive, "Not A Name")).status_code == 422

    assert not library_root(library=MOVED).exists()
    assert not list((memory_db.tmp_path / "downloads").iterdir())
    assert (await client.get("/libraries")).json()["active"] == "default"
