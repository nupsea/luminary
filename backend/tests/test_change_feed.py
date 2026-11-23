"""The change feed a paired client syncs from (#450).

Triggers record each write to notes and documents in the writing transaction, one row per entity,
so `since=0` lists the library and a cursor sees every later write exactly once, in order.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text, update

from app.db_init import init_database
from app.main import app
from app.models import ChangeLogModel, DocumentModel, NoteModel
from app.services import devices
from app.services.change_feed import TOMBSTONE_RETENTION, prune_tombstones
from tests.factories import make_document, make_note
from tests.test_drop_content_type_migration import _migrate

OWN = "http://127.0.0.1"
PHONE = {"X-Forwarded-For": "10.0.0.5"}
BEFORE_FEED = "b81e4c2f9d07"


@pytest.fixture
async def client(memory_db):
    devices._active_code = None
    devices._attempts.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url=OWN) as c:
        yield c


async def _feed(client: AsyncClient, **params) -> dict:
    resp = await client.get("/changes", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ops(page: dict) -> list[tuple[str, str, str]]:
    return [(c["entity"], c["entity_id"], c["op"]) for c in page["changes"]]


async def test_a_cursor_sees_each_later_write_once_and_in_order(client, memory_db):
    start = await _feed(client)
    note = (await client.post("/notes", json={"content": "First."})).json()["id"]
    await client.patch(f"/notes/{note}", json={"content": "Second."})
    await client.patch(f"/notes/{note}", json={"content": "Third."})
    other = (await client.post("/notes", json={"content": "Other."})).json()["id"]
    await client.delete(f"/notes/{note}")

    page = await _feed(client, epoch=start["epoch"], since=start["next"])
    assert _ops(page) == [("note", other, "upsert"), ("note", note, "delete")]
    assert not page["resync"] and not page["more"]
    assert page["next"] == page["changes"][-1]["seq"]
    assert await _feed(client, epoch=start["epoch"], since=page["next"]) == {
        **page,
        "changes": [],
    }


async def test_since_zero_lists_every_live_note_and_document(client, memory_db):
    async with memory_db.factory() as session:
        session.add_all([make_document(id="d1"), make_note(id="n1"), make_note(id="n2")])
        await session.commit()
    page = await _feed(client)
    assert {(e, i) for e, i, op in _ops(page) if op == "upsert"} == {
        ("document", "d1"),
        ("note", "n1"),
        ("note", "n2"),
    }


async def test_paging_hands_over_at_next(client, memory_db):
    async with memory_db.factory() as session:
        session.add_all([make_note(id=f"n{i}") for i in range(5)])
        await session.commit()
    first = await _feed(client, limit=2)
    assert len(first["changes"]) == 2 and first["more"]
    rest = await _feed(client, epoch=first["epoch"], since=first["next"], limit=10)
    assert not rest["more"]
    seen = [c["entity_id"] for c in first["changes"] + rest["changes"]]
    assert sorted(seen) == [f"n{i}" for i in range(5)]


async def test_writes_outside_the_orm_are_recorded(client, memory_db):
    """Repo-level recording would miss these: Core bulk statements and raw SQL."""
    async with memory_db.factory() as session:
        session.add_all([make_note(id="bulk"), make_document(id="raw"), make_note(id="again")])
        await session.commit()
        await session.execute(delete(NoteModel).where(NoteModel.id == "again"))
        await session.commit()
    start = await _feed(client)
    async with memory_db.factory() as session:
        await session.execute(update(NoteModel).values(title="Renamed"))
        await session.execute(text("UPDATE documents SET title = 'Raw' WHERE id = 'raw'"))
        # Re-created over its own tombstone, under an outer OR clause: SQLite applies the
        # outer clause to the trigger's statements too, so an OR REPLACE there becomes OR
        # IGNORE and the tombstone would stand.
        await session.execute(
            text(
                "INSERT OR IGNORE INTO notes (id, content, tags, created_at, updated_at) "
                "VALUES ('again', 'x', '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        await session.execute(delete(DocumentModel).where(DocumentModel.id == "raw"))
        await session.commit()
    page = await _feed(client, epoch=start["epoch"], since=start["next"])
    assert _ops(page) == [
        ("note", "bulk", "upsert"),
        ("note", "again", "upsert"),
        ("document", "raw", "delete"),
    ]


async def test_a_write_to_no_column_a_client_shows_is_not_a_change(client, memory_db):
    async with memory_db.factory() as session:
        session.add(make_document(id="d1"))
        await session.commit()
    start = await _feed(client)
    async with memory_db.factory() as session:
        await session.execute(
            update(DocumentModel).values(last_accessed_at=datetime.now(UTC), file_hash="abc")
        )
        await session.commit()
    assert (await _feed(client, epoch=start["epoch"], since=start["next"]))["changes"] == []


async def test_a_cursor_the_feed_cannot_answer_resyncs_from_zero(client, memory_db):
    async with memory_db.factory() as session:
        session.add(make_note(id="n1"))
        await session.commit()
    page = await _feed(client)
    full = _ops(page)

    for params in (
        {"epoch": "another-library", "since": page["next"]},
        {"epoch": page["epoch"], "since": page["next"] + 100},
        {"since": page["next"]},
    ):
        resynced = await _feed(client, **params)
        assert resynced["resync"], params
        assert _ops(resynced) == full


async def test_a_cursor_older_than_a_pruned_deletion_resyncs(client, memory_db):
    async with memory_db.factory() as session:
        session.add_all([make_note(id="gone"), make_note(id="kept")])
        await session.commit()
    before = await _feed(client)
    async with memory_db.factory() as session:
        await session.execute(delete(NoteModel).where(NoteModel.id == "gone"))
        await session.commit()
    after = await _feed(client, epoch=before["epoch"], since=before["next"])

    assert await prune_tombstones(datetime.now(UTC) + TOMBSTONE_RETENTION + timedelta(days=1)) == 1
    stale = await _feed(client, epoch=before["epoch"], since=before["next"])
    assert stale["resync"]
    assert ("note", "gone", "delete") not in _ops(stale)
    current = await _feed(client, epoch=after["epoch"], since=after["next"])
    assert not current["resync"]


async def test_a_paired_device_reads_the_feed(client, memory_db):
    code = (await client.post("/devices/pairing-code")).json()["code"]
    paired = await client.post("/devices/pair", json={"code": code, "name": "phone"}, headers=PHONE)
    device = {**PHONE, "Authorization": f"Bearer {paired.json()['token']}"}
    resp = await client.get("/changes", headers=device)
    assert resp.status_code == 200, resp.text
    assert (await client.get("/changes", headers=PHONE)).status_code == 401


async def test_the_upgrade_lists_the_existing_library_and_installs_the_triggers(memory_db):
    await init_database(memory_db.engine)  # the shared template is built from the models
    await _migrate(memory_db.engine, BEFORE_FEED)
    async with memory_db.engine.begin() as conn:
        tables = {r[0] for r in await conn.execute(text("SELECT name FROM sqlite_master"))}
        assert "change_log" not in tables and "change_feed_notes_insert" not in tables
        await conn.execute(
            text(
                "INSERT INTO notes (id, content, tags, created_at, updated_at) "
                "VALUES ('old', 'x', '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    await init_database(memory_db.engine)

    async with memory_db.factory() as session:
        rows = (await session.execute(select(ChangeLogModel))).scalars().all()
        assert [(r.entity, r.entity_id, r.op) for r in rows] == [("note", "old", "upsert")]
        await session.execute(update(NoteModel).values(content="y"))
        await session.commit()
        rows = (await session.execute(select(ChangeLogModel))).scalars().all()
        assert len(rows) == 1 and rows[0].seq > 1


async def test_the_migration_and_the_models_install_the_same_triggers(memory_db, tmp_path):
    from app.database import make_engine

    async def triggers(engine) -> dict[str, str]:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")
            )
            return {name: " ".join(sql.split()) for name, sql in result}

    from_models = await triggers(memory_db.engine)
    migrated = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}")
    try:
        await init_database(migrated)
        assert await triggers(migrated) == from_models
    finally:
        await migrated.dispose()
    assert len(from_models) == 6
