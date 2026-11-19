"""The app works in its active library, and a library moves between machines whole.

Through HTTP: a switch moves the app's reads and writes and nothing else (a paired device
stays in its own library, the device registry stays in the default one); the choice
survives a restart; an export imported on another machine answers as the original.
"""

import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import app.services.devices as devices
from app.database import get_session_factory
from app.main import app
from app.runtime.library_work import stop_library
from app.services import libraries, sync_folders
from app.storage import library_root, machine_root
from tests.test_library_binding import OWN, _pair_into, _write
from tests.test_library_context import _close
from tests.test_library_snapshot import _head

WORK = "work"
MOVED = "moved"
KIDS = "kids"
COPY = "copy"


@pytest.fixture
async def client(memory_db, monkeypatch):
    import app.routers.documents as documents_router

    async def _no_pipeline(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(documents_router, "run_ingestion", _no_pipeline)
    # Path.home() reads USERPROFILE on Windows.
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(memory_db.tmp_path / "home"))
    devices._active_code = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url=OWN) as c:
        yield c
    devices._active_code = None
    libraries._active.clear()
    await _close(WORK, MOVED, KIDS, COPY)


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

    # Not by deleting its database: Windows refuses while the engine holds it open.
    libraries.mark_removed(WORK)
    libraries._active.clear()
    assert libraries.active_library() == "default"

    (machine_root() / libraries.ACTIVE_FILE).write_text('{"library": "nowhere"}')
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


async def _export(client: AsyncClient, library: str, destination: str | None = None) -> dict:
    body = None if destination is None else {"destination": destination}
    resp = await client.post(f"/libraries/{library}/export", json=body)
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
    folder = memory_db.tmp_path / "home" / sync_folders.EXPORT_FOLDER
    assert archive.parent == folder
    assert [p.name for p in folder.iterdir()] == [archive.name]  # no partial left behind
    assert exported["destination"] == sync_folders.EXPORTS
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


async def test_a_library_is_named_and_counted_and_its_name_travels(client):
    await _write(client, {}, "Odyssey")
    resp = await client.post(
        "/libraries", json={"library": WORK, "name": "  Work  ", "color": "blue"}
    )
    assert resp.status_code == 201, resp.text
    listed = {lib["id"]: lib for lib in resp.json()["libraries"]}
    assert listed[WORK]["name"] == "Work"
    assert listed[WORK]["color"] == "blue"
    assert listed[WORK]["contents"] == {"documents": 0, "flashcards": 0, "notes": 0}
    assert listed["default"]["name"] is None
    assert listed["default"]["contents"] == {"documents": 1, "flashcards": 1, "notes": 1}

    renamed = await client.patch(f"/libraries/{WORK}", json={"name": "Office", "color": "teal"})
    assert renamed.status_code == 200, renamed.text
    work = next(lib for lib in renamed.json()["libraries"] if lib["id"] == WORK)
    assert (work["name"], work["color"]) == ("Office", "teal")
    assert (await client.patch(f"/libraries/{WORK}", json={"color": "plaid"})).status_code == 422
    assert (await client.patch("/libraries/nowhere", json={"name": "x"})).status_code == 404

    archive = Path((await _export(client, WORK))["path"])
    assert archive.name.startswith("luminary-office-")
    resp = await _import(client, archive, MOVED)
    assert resp.status_code == 201, resp.text
    # Imported beside the library it came from, so made distinct; on another machine it is "Office".
    assert (resp.json()["name"], resp.json()["color"]) == ("Office (moved)", "teal")
    again = await _import(client, archive, COPY)
    assert again.status_code == 201, again.text
    assert again.json()["name"] == "Office (copy)"
    names = [lib["name"] for lib in (await client.get("/libraries")).json()["libraries"]]
    assert names.count("Office") == 1


def _sync_home(home: Path) -> dict[str, Path]:
    storage = home / "Library" / "CloudStorage"
    folders = {
        "icloud": home / "Library" / "Mobile Documents" / "com~apple~CloudDocs",
        "dropbox": storage / "Dropbox",
        "google-drive": storage / "GoogleDrive-reader@example.com" / "My Drive",
        "onedrive": storage / "OneDrive-Personal",
        "sharepoint": storage / "OneDrive-SharedLibraries-Contoso",
    }
    for folder in folders.values():
        folder.mkdir(parents=True)
    if sys.platform != "win32":  # a symlink needs a privilege there
        # The legacy home-folder link to the same Dropbox is one destination, not two.
        (home / "Dropbox").symlink_to(storage / "Dropbox")
    return folders


async def test_a_library_moves_through_a_sync_folder(client, memory_db, monkeypatch):
    built: list[Path] = []
    take = libraries.take_snapshot

    async def _spy(dest: Path):
        built.append(dest)
        return await take(dest)

    monkeypatch.setattr(libraries, "take_snapshot", _spy)
    home = memory_db.tmp_path / "home"
    folders = _sync_home(home)
    await _write(client, {}, "Odyssey")
    await _ready()

    dests = (await client.get("/libraries/destinations")).json()["destinations"]
    assert [d["kind"] for d in dests] == [
        "exports",
        "icloud",
        "dropbox",
        "google-drive",
        "onedrive",
    ]
    by_kind = {d["kind"]: d for d in dests}
    assert by_kind["google-drive"]["name"] == "Google Drive (reader@example.com)"
    assert by_kind["onedrive"]["name"] == "OneDrive (Personal)"
    dropbox = by_kind["dropbox"]
    assert Path(dropbox["path"]) == folders["dropbox"] / sync_folders.SYNC_SUBFOLDER

    exported = await _export(client, "default", dropbox["id"])
    assert Path(exported["path"]).parent == Path(dropbox["path"])
    assert exported["destination_name"] == "Dropbox"
    # Built outside the sync folder, so its client never uploads a half-written archive.
    assert built[0].parent == memory_db.tmp_path / "downloads"
    assert [p.name for p in Path(dropbox["path"]).iterdir()] == [exported["name"]]
    assert not list((memory_db.tmp_path / "downloads").iterdir())

    dests = (await client.get("/libraries/destinations")).json()["destinations"]
    listed = next(d for d in dests if d["id"] == dropbox["id"])["archives"]
    assert [a["name"] for a in listed] == [exported["name"]]
    assert listed[0]["bytes"] == exported["bytes"]

    resp = await client.post(
        "/libraries/import-from-folder",
        json={"destination": dropbox["id"], "name": exported["name"], "library": MOVED},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["contents"] == exported["contents"]
    assert resp.json()["active"] is False
    assert Path(exported["path"]).is_file()  # the archive stays for another machine


async def test_only_listed_archives_in_known_folders_are_reachable(client, memory_db, monkeypatch):
    _sync_home(memory_db.tmp_path / "home")
    await _ready()
    exported = await _export(client, "default")
    secret = memory_db.tmp_path / "home" / "secret.tar.gz"
    secret.write_bytes(b"not yours")

    def _import_from(destination: str, name: str):
        body = {"destination": destination, "name": name, "library": MOVED}
        return client.post("/libraries/import-from-folder", json=body)

    assert (await _import_from("nowhere", exported["name"])).status_code == 404
    assert (await _import_from("exports", "../secret.tar.gz")).status_code == 404
    assert (await _import_from("exports", "secret.tar.gz")).status_code == 404
    assert (
        await client.post("/libraries/default/export", json={"destination": "/tmp"})
    ).status_code == 404
    assert not library_root(library=MOVED).exists()

    shown: list[list[str]] = []
    monkeypatch.setattr(sync_folders.subprocess, "run", lambda argv, **_: shown.append(argv))
    ok = await client.post(
        "/libraries/reveal", json={"destination": "exports", "name": exported["name"]}
    )
    assert ok.status_code == 204, ok.text
    # The file selected where the platform can, else its folder opened (xdg-open on Linux).
    assert str(Path(exported["path"]).parent) in " ".join(shown[0])
    refused = await client.post(
        "/libraries/reveal", json={"destination": "exports", "name": "x.tar.gz"}
    )
    assert refused.status_code == 404
    assert len(shown) == 1


async def test_a_removed_library_is_gone_and_the_rest_are_untouched(client):
    await _write(client, {}, "Odyssey")
    await client.post("/libraries", json={"library": KIDS, "name": "Kids"})
    assert (await client.delete("/libraries/default")).status_code == 422
    await _switch(client, KIDS)
    assert (await client.delete(f"/libraries/{KIDS}")).status_code == 409
    await _switch(client, "default")
    device = await _pair_into(client, KIDS)
    paired = await client.delete(f"/libraries/{KIDS}")
    assert paired.status_code == 409 and "unpair" in paired.json()["detail"]
    listed = (await client.get("/devices")).json()
    assert (await client.delete(f"/devices/{listed[0]['id']}")).status_code == 204
    assert (await client.get("/documents", headers=device)).status_code == 401

    # Served by this process: hidden now, deleted at the next start.
    resp = await client.delete(f"/libraries/{KIDS}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"library": KIDS, "removed_now": False}
    assert [lib["id"] for lib in (await client.get("/libraries")).json()["libraries"]] == [
        "default"
    ]
    assert (await client.put("/libraries/active", json={"library": KIDS})).status_code == 404
    assert (await client.post("/libraries", json={"library": KIDS})).status_code == 409
    assert library_root(library=KIDS).exists()

    await _close(KIDS)  # as a restart does: Windows will not delete a database held open
    assert libraries.purge_removed_libraries() == [KIDS]
    assert not library_root(library=KIDS).exists()
    assert await _titles(client) == ["Odyssey"]


async def test_a_library_not_open_in_this_process_is_deleted_at_once(client):
    await client.post("/libraries", json={"library": KIDS})
    await stop_library(KIDS)  # as after a restart: listed, never served
    assert KIDS in [lib["id"] for lib in (await client.get("/libraries")).json()["libraries"]]

    resp = await client.delete(f"/libraries/{KIDS}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["removed_now"] is True
    assert not library_root(library=KIDS).exists()
    assert (await client.post("/libraries", json={"library": KIDS})).status_code == 201
