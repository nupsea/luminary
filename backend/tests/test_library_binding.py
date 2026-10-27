"""Through HTTP, a request runs in its principal's library and sees nothing of another's (#388).

The app's own origin is the default library; a device pairs into the library whose app
showed the code. Each side writes a document, a note, a card and a graph entity, and
reads back only its own.
"""

import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.routers.documents as documents_router
import app.services.devices as devices
from app.database import get_session_factory
from app.library import use_library
from app.main import app
from app.models import DeviceModel, GraphEntityModel
from app.storage import library_root
from tests.test_library_context import _close

OWN = "http://127.0.0.1:7820"
OTHER = "second"


@pytest.fixture
async def client(memory_db, monkeypatch):
    async def _no_pipeline(*_args, **_kwargs) -> None:
        return None

    # The pipeline is not under test: only where the upload and its row land.
    monkeypatch.setattr(documents_router, "run_ingestion", _no_pipeline)
    devices._active_code = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url=OWN) as c:
        yield c
    devices._active_code = None
    await _close(OTHER)


async def _pair_into(client: AsyncClient, library: str) -> dict[str, str]:
    with use_library(library):
        code, _ = devices.issue_pairing_code()
    resp = await client.post(
        "/devices/pair",
        json={"code": code, "name": "phone"},
        headers={"Origin": "https://phone.example"},
    )
    assert resp.status_code == 201, resp.text
    return {"Origin": "https://phone.example", "Authorization": f"Bearer {resp.json()['token']}"}


async def _write(client: AsyncClient, headers: dict[str, str], title: str) -> str:
    resp = await client.post(
        "/documents/ingest",
        files={"file": (f"{title}.txt", f"{title} is a story told twice.".encode(), "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["document_id"]
    note = await client.post(
        "/notes",
        json={"document_id": doc_id, "content": f"About {title}.", "tags": ["reading"]},
        headers=headers,
    )
    assert note.status_code == 201, note.text
    card = await client.post(
        "/flashcards/create-trace",
        json={
            "document_id": doc_id,
            "question": f"Who tells {title}?",
            "answer": "The narrator.",
            "source_excerpt": f"{title} is a story told twice.",
        },
        headers=headers,
    )
    assert card.status_code == 201, card.text
    return doc_id


async def _add_entity(library: str, doc_id: str, name: str) -> None:
    # The graph is written by the pipeline, which is stubbed; its read path is what is tested.
    with use_library(library):
        async with get_session_factory()() as session:
            session.add(
                GraphEntityModel(id=str(uuid.uuid4()), document_id=doc_id, name=name, type="PERSON")
            )
            await session.commit()


async def _seen(client: AsyncClient, headers: dict[str, str], doc_ids: list[str]) -> dict:
    documents = (await client.get("/documents", headers=headers)).json()["items"]
    notes = (await client.get("/notes", headers=headers)).json()
    cards = {d: (await client.get(f"/flashcards/{d}", headers=headers)).json() for d in doc_ids}
    entities = {
        d: (
            await client.get(f"/graph/entities/{d}", params={"type": "PERSON"}, headers=headers)
        ).json()["entities"]
        for d in doc_ids
    }
    return {
        "documents": sorted(d["id"] for d in documents),
        "notes": sorted(n["document_id"] for n in notes),
        "cards": sorted(d for d, rows in cards.items() for _ in rows),
        "entities": sorted(e["name"] for rows in entities.values() for e in rows),
    }


async def test_a_device_sees_only_the_library_it_paired_into(client, memory_db):
    device = await _pair_into(client, OTHER)
    own = await _write(client, {}, "Odyssey")
    other = await _write(client, device, "Iliad")
    await _add_entity("default", own, "Penelope")
    await _add_entity(OTHER, other, "Hector")

    assert await _seen(client, {}, [own, other]) == {
        "documents": [own],
        "notes": [own],
        "cards": [own],
        "entities": ["Penelope"],
    }
    assert await _seen(client, device, [own, other]) == {
        "documents": [other],
        "notes": [other],
        "cards": [other],
        "entities": ["Hector"],
    }
    assert (await client.get(f"/documents/{own}", headers=device)).status_code == 404
    uploads = {p.name for p in (library_root(library=OTHER) / "raw").iterdir()}
    assert uploads == {f"{other}.txt"}
    assert not (Path(memory_db.tmp_path) / "raw" / f"{other}.txt").exists()


async def test_the_registry_stays_in_the_default_library(client, memory_db):
    device = await _pair_into(client, OTHER)
    assert (await client.get("/documents", headers=device)).status_code == 200

    async with memory_db.factory() as session:
        rows = (await session.execute(select(DeviceModel))).scalars().all()
    assert [(d.name, d.library) for d in rows] == [("phone", OTHER)]
    with use_library(OTHER):
        async with get_session_factory()() as session:
            assert (await session.execute(select(DeviceModel))).scalars().all() == []


async def test_a_revoked_device_is_refused_before_its_library_is_reached(client):
    device = await _pair_into(client, OTHER)
    device_id = (await client.get("/devices")).json()[0]["id"]
    assert (await client.delete(f"/devices/{device_id}")).status_code == 204

    assert (await client.get("/documents", headers=device)).status_code == 401
