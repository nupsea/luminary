"""A retried write does not happen twice, and an edit never overwrites a newer one (#451).

A phone's outbox retries whatever it is not sure arrived. With `Idempotency-Key` a retry
replays the first response; with `rev` an edit made against an older revision is refused with
the current note, so the client keeps its text as a conflict copy rather than losing either.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from app.db_init import init_database
from app.main import app
from app.models import IdempotencyKeyModel, NoteModel
from app.repos.idempotency_repo import IdempotencyRepo
from app.runtime.idempotency import KEY_RETENTION, prune_keys
from app.services import devices
from tests.test_drop_content_type_migration import _migrate

PHONE = {"X-Forwarded-For": "10.0.0.5"}
BEFORE = "ac7d219e984f"


@pytest.fixture
async def client(memory_db):
    devices._active_code = None
    devices._attempts.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        yield c


async def _notes(memory_db) -> int:
    async with memory_db.factory() as session:
        return await session.scalar(select(func.count()).select_from(NoteModel))


async def _device(client) -> dict[str, str]:
    code = (await client.post("/devices/pairing-code")).json()["code"]
    resp = await client.post("/devices/pair", json={"code": code, "name": "phone"}, headers=PHONE)
    return {**PHONE, "Authorization": f"Bearer {resp.json()['token']}"}


async def test_a_retried_create_replays_the_first_response(client, memory_db):
    key = {"Idempotency-Key": "outbox-1"}
    first = await client.post("/notes", json={"content": "Written offline."}, headers=key)
    again = await client.post("/notes", json={"content": "Written offline."}, headers=key)
    assert first.status_code == again.status_code == 201
    assert again.json() == first.json()
    assert again.headers["idempotent-replayed"] == "true"
    assert await _notes(memory_db) == 1


async def test_a_key_reused_for_another_request_is_refused(client, memory_db):
    key = {"Idempotency-Key": "outbox-2"}
    await client.post("/notes", json={"content": "One."}, headers=key)
    other = await client.post("/notes", json={"content": "Another."}, headers=key)
    assert other.status_code == 422
    assert "different request" in other.json()["detail"]
    assert await _notes(memory_db) == 1


async def test_a_duplicate_while_the_first_runs_is_refused_not_run(client, memory_db):
    body = b'{"content": "Racing."}'
    async with memory_db.factory() as session:
        request_hash = await _hash_of(client, body)
        await IdempotencyRepo(session).reserve("local", "outbox-3", request_hash)
    resp = await client.post(
        "/notes",
        content=body,
        headers={"Idempotency-Key": "outbox-3", "Content-Type": "application/json"},
    )
    assert resp.status_code == 409
    assert await _notes(memory_db) == 0


async def _hash_of(client, body: bytes) -> str:
    from starlette.requests import Request

    from app.runtime.idempotency import _request_hash

    scope = {"type": "http", "method": "POST", "path": "/notes", "query_string": b"", "headers": []}

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return await _request_hash(Request(scope, receive))


async def test_keys_belong_to_whoever_sent_them(client, memory_db):
    device = await _device(client)
    key = {"Idempotency-Key": "same-key"}
    await client.post("/notes", json={"content": "From the desktop."}, headers=key)
    await client.post("/notes", json={"content": "From the phone."}, headers={**device, **key})
    assert await _notes(memory_db) == 2


async def test_a_failed_write_does_not_hold_its_key(client, memory_db):
    key = {"Idempotency-Key": "review-1"}
    for _ in range(2):
        resp = await client.post("/flashcards/missing/review", json={"rating": "good"}, headers=key)
        assert resp.status_code == 404
    async with memory_db.factory() as session:
        assert (await session.execute(select(IdempotencyKeyModel))).scalars().all() == []


async def test_an_edit_against_an_older_revision_is_refused_with_the_current_note(client):
    note = (await client.post("/notes", json={"content": "v0"})).json()
    assert note["rev"] == 0
    first = await client.patch(f"/notes/{note['id']}", json={"content": "v1", "rev": 0})
    assert first.status_code == 200 and first.json()["rev"] == 1

    stale = await client.patch(f"/notes/{note['id']}", json={"content": "lost?", "rev": 0})
    assert stale.status_code == 409
    assert stale.json()["note"]["content"] == "v1" and stale.json()["note"]["rev"] == 1
    current = (await client.get(f"/notes/{note['id']}")).json()
    assert current["content"] == "v1" and current["rev"] == 1

    unchecked = await client.patch(f"/notes/{note['id']}", json={"content": "v2"})
    assert unchecked.status_code == 200 and unchecked.json()["rev"] == 2


async def test_a_retried_edit_moves_the_revision_once(client):
    note = (await client.post("/notes", json={"content": "v0"})).json()
    key = {"Idempotency-Key": "edit-1"}
    for _ in range(2):
        resp = await client.patch(
            f"/notes/{note['id']}", json={"content": "v1", "rev": 0}, headers=key
        )
        assert resp.status_code == 200 and resp.json()["rev"] == 1


async def test_a_device_deletes_a_note_and_the_feed_records_it(client):
    device = await _device(client)
    note = (await client.post("/notes", json={"content": "Gone soon."}, headers=device)).json()
    start = (await client.get("/changes", headers=device)).json()
    assert (await client.delete(f"/notes/{note['id']}", headers=device)).status_code == 204
    page = (
        await client.get(
            "/changes", params={"epoch": start["epoch"], "since": start["next"]}, headers=device
        )
    ).json()
    assert [(c["entity_id"], c["op"]) for c in page["changes"]] == [(note["id"], "delete")]


async def test_old_keys_are_pruned(client, memory_db):
    await client.post("/notes", json={"content": "x"}, headers={"Idempotency-Key": "old"})
    assert await prune_keys(datetime.now(UTC) + KEY_RETENTION + timedelta(days=1)) == 1
    async with memory_db.factory() as session:
        assert (await session.execute(select(IdempotencyKeyModel))).scalars().all() == []


async def test_the_upgrade_gives_every_note_a_revision_and_keeps_the_feed(memory_db):
    await init_database(memory_db.engine)  # the shared template is built from the models
    await _migrate(memory_db.engine, BEFORE)
    async with memory_db.engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO notes (id, content, tags, created_at, updated_at) "
                "VALUES ('old', 'x', '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    await init_database(memory_db.engine)
    async with memory_db.engine.begin() as conn:
        assert (await conn.execute(text("SELECT rev FROM notes"))).scalar() == 0
        triggers = await conn.execute(
            text("SELECT count(*) FROM sqlite_master WHERE type = 'trigger'")
        )
        assert triggers.scalar() == 6
