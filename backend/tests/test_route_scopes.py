"""A paired device acts only within the scopes its routes declare (#532).

A route is the app's alone unless it declares a device scope (`device_scope`), and
`authorize_route` admits a device only to a route whose scope its token holds. Every
refusal test asserts the local-only message, so it fails when the dependency is removed.
"""

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, update

import app.routers.qa as qa_router
import app.services.blog_service as blog_service
import app.services.devices as devices
from app.db_init import init_database
from app.exceptions import TooManyRequests
from app.main import app
from app.models import DeviceModel, NoteModel
from app.runtime.request_auth import (
    RequestAuthMiddleware,
    authorize_route,
    require_this_computer,
    route_scopes,
)
from app.types import DEFAULT_DEVICE_SCOPES, DEVICE_SCOPES
from tests.test_drop_content_type_migration import _migrate

OWN = "http://127.0.0.1:7820"
PHONE = {"Origin": "https://phone.example"}
LOCAL_ONLY = "Only Luminary on this computer can do this; a paired device cannot."
BEFORE_SCOPES = "7f6bcd0f8881"

# Everything a device can reach. A change here is a change to what a lost phone can do.
DEVICE_ROUTES = {
    # notes:write
    ("DELETE", "/notes/{note_id}/links/{target_note_id}", "notes:write"),
    ("PATCH", "/notes/{note_id}", "notes:write"),
    ("POST", "/images/notes", "notes:write"),
    ("POST", "/notes", "notes:write"),
    ("POST", "/notes/{note_id}/links", "notes:write"),
    ("PUT", "/notes/{note_id}", "notes:write"),
    # read
    ("GET", "/documents", "read"),
    ("GET", "/documents/facets", "read"),
    ("GET", "/documents/{document_id}", "read"),
    ("GET", "/documents/{document_id}/asset/{asset_path:path}", "read"),
    ("GET", "/documents/{document_id}/audio", "read"),
    ("GET", "/documents/{document_id}/chunks", "read"),
    ("GET", "/documents/{document_id}/code_snippets", "read"),
    ("GET", "/documents/{document_id}/conversation", "read"),
    ("GET", "/documents/{document_id}/cover", "read"),
    ("GET", "/documents/{document_id}/diagnostics", "read"),
    ("GET", "/documents/{document_id}/epub/chapter/{chapter_index}", "read"),
    ("GET", "/documents/{document_id}/epub/toc", "read"),
    ("GET", "/documents/{document_id}/file", "read"),
    ("GET", "/documents/{document_id}/images", "read"),
    ("GET", "/documents/{document_id}/objectives", "read"),
    ("GET", "/documents/{document_id}/overview", "read"),
    ("GET", "/documents/{document_id}/pdf-meta", "read"),
    ("GET", "/documents/{document_id}/position", "read"),
    ("GET", "/documents/{document_id}/progress", "read"),
    ("GET", "/documents/{document_id}/search", "read"),
    ("GET", "/documents/{document_id}/status", "read"),
    ("GET", "/documents/{document_id}/video", "read"),
    ("GET", "/flashcards/audit/{document_id}", "read"),
    ("GET", "/flashcards/decks", "read"),
    ("GET", "/flashcards/entity-pairs", "read"),
    ("GET", "/flashcards/grounding", "read"),
    ("GET", "/flashcards/health/{document_id}", "read"),
    ("GET", "/flashcards/search", "read"),
    ("GET", "/flashcards/{card_id}/source-context", "read"),
    ("GET", "/flashcards/{document_id}", "read"),
    ("GET", "/flashcards/{document_id}/export/csv", "read"),
    ("GET", "/flashcards/{document_id}/headroom", "read"),
    ("GET", "/health", "read"),
    ("GET", "/healthz", "read"),
    ("GET", "/images/local/{doc_id}/{filename}", "read"),
    ("GET", "/images/{image_id}/raw", "read"),
    ("GET", "/notes", "read"),
    ("GET", "/openapi.json", "read"),
    ("GET", "/notes/autocomplete", "read"),
    ("GET", "/notes/cluster/suggestions", "read"),
    ("GET", "/notes/flashcards", "read"),
    ("GET", "/notes/flashcards/generate/preview", "read"),
    ("GET", "/notes/groups", "read"),
    ("GET", "/notes/search", "read"),
    ("GET", "/notes/{note_id}", "read"),
    ("GET", "/notes/{note_id}/entities", "read"),
    ("GET", "/notes/{note_id}/export", "read"),
    ("GET", "/notes/{note_id}/links", "read"),
    ("GET", "/search", "read"),
    ("GET", "/sections/{document_id}", "read"),
    ("GET", "/sections/{document_id}/chapters", "read"),
    ("GET", "/sections/{document_id}/content", "read"),
    ("GET", "/sections/{document_id}/content/{section_id}", "read"),
    ("GET", "/study/calibration-stats", "read"),
    ("GET", "/study/collections/{collection_id}/dashboard", "read"),
    ("GET", "/study/decay-debt", "read"),
    ("GET", "/study/due", "read"),
    ("GET", "/study/due-count", "read"),
    ("GET", "/study/gaps/{document_id}", "read"),
    ("GET", "/study/history", "read"),
    ("GET", "/study/misconception-stats", "read"),
    ("GET", "/study/section-heatmap", "read"),
    ("GET", "/study/sections/{document_id}", "read"),
    ("GET", "/study/session-plan", "read"),
    ("GET", "/study/sessions", "read"),
    ("GET", "/study/sessions/open", "read"),
    ("GET", "/study/sessions/{session_id}/cards", "read"),
    ("GET", "/study/sessions/{session_id}/remaining-cards", "read"),
    ("GET", "/study/sessions/{session_id}/teachback-results", "read"),
    ("GET", "/study/stats/{document_id}", "read"),
    ("GET", "/study/struggling", "read"),
    ("GET", "/study/teachback/results", "read"),
    ("GET", "/study/topics/{document_id}", "read"),
    ("HEAD", "/documents/{document_id}/asset/{asset_path:path}", "read"),
    ("POST", "/qa", "read"),
    # reviews:write
    ("POST", "/flashcards/{card_id}/review", "reviews:write"),
    ("POST", "/study/sessions/start", "reviews:write"),
    ("POST", "/study/sessions/{session_id}/end", "reviews:write"),
    ("POST", "/study/sessions/{session_id}/reopen", "reviews:write"),
}


@pytest.fixture(autouse=True)
def _fresh_pairing_state():
    devices._active_code = None
    devices._attempts.clear()
    yield
    devices._active_code = None
    devices._attempts.clear()


@pytest.fixture
async def client(memory_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=OWN) as c:
        yield c


async def _device(client: AsyncClient) -> dict[str, str]:
    code = (await client.post("/devices/pairing-code")).json()["code"]
    resp = await client.post("/devices/pair", json={"code": code, "name": "phone"}, headers=PHONE)
    assert resp.status_code == 201, resp.text
    return {**PHONE, "Authorization": f"Bearer {resp.json()['token']}"}


def _declared() -> set[tuple[str, str, str]]:
    found = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        scopes = route_scopes(route)
        assert len(scopes) <= 1, f"{route.path} declares {scopes}"
        assert set(scopes) <= set(DEVICE_SCOPES), f"{route.path} declares {scopes}"
        found |= {(method, route.path, scopes[0]) for method in route.methods if scopes}
    return found


def test_every_route_a_device_reaches_is_one_this_test_names():
    # Default-deny: a route missing here is local-only, so dropping a declaration or adding
    # one both fail until this map is changed on purpose.
    assert _declared() == DEVICE_ROUTES


def test_a_route_that_loses_its_declaration_is_caught(monkeypatch):
    create = next(
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.path == "/notes" and "POST" in r.methods
    )
    kept = [d for d in create.dependant.dependencies if not hasattr(d.call, "scope")]
    monkeypatch.setattr(create.dependant, "dependencies", kept)
    assert ("POST", "/notes", "notes:write") not in _declared()


# Inputs that do nothing if they get through: an unknown component or connector, an
# invalid URL, a key request without a key. A regressed gate must fail here, not install.
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PATCH", "/settings/llm", {"engine_mode": "cloud"}),
        ("PATCH", "/settings", {"planted": "yes"}),
        ("POST", "/settings/llm/key", {"provider": "none"}),
        ("POST", "/setup/components/no-such-component/install", None),
        ("DELETE", "/setup/components/no-such-component", None),
        ("POST", "/connectors/catalogue/no-such-connector/install", None),
        ("PUT", "/connectors/no-such-connector/credentials", {"values": {}}),
        ("POST", "/blog/publish", {}),
        ("POST", "/blog/push", None),
        ("POST", "/admin/notes/reindex", None),
        ("DELETE", "/documents/no-such-document", None),
        ("POST", "/documents/ingest-url", {"url": "not a url"}),
        ("GET", "/libraries", None),
        ("GET", "/devices", None),
        ("POST", "/devices/pairing-code", None),
    ],
)
async def test_a_device_is_refused_every_local_only_class(client, monkeypatch, method, path, body):
    async def _never(*_args, **_kwargs):
        raise AssertionError("a device reached git push")

    monkeypatch.setattr(blog_service, "git_push", _never)
    device = await _device(client)
    resp = await client.request(method, path, json=body, headers=device)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == LOCAL_ONLY


async def test_the_app_itself_keeps_every_route(client):
    assert (await client.get("/libraries")).status_code == 200
    assert (await client.get("/devices")).status_code == 200


async def test_a_device_reads_writes_notes_and_reviews_within_its_scopes(client):
    device = await _device(client)
    created = await client.post("/notes", json={"content": "From the phone."}, headers=device)
    assert created.status_code == 201, created.text
    note_id = created.json()["id"]
    assert (await client.get(f"/notes/{note_id}", headers=device)).status_code == 200
    edited = await client.patch(f"/notes/{note_id}", json={"content": "Edited."}, headers=device)
    assert edited.status_code == 200, edited.text
    started = await client.post(
        "/study/sessions/start", json={"document_id": None, "mode": "flashcard"}, headers=device
    )
    assert started.status_code in (200, 201), started.text
    refused = await client.delete(f"/notes/{note_id}", headers=device)
    assert refused.status_code == 403 and refused.json()["detail"] == LOCAL_ONLY


async def test_a_device_without_a_scope_is_refused_what_it_needs(client, memory_db):
    device = await _device(client)
    async with memory_db.factory() as session:
        await session.execute(update(DeviceModel).values(scopes=["read"]))
        await session.commit()

    assert (await client.get("/notes", headers=device)).status_code == 200
    resp = await client.post("/notes", json={"content": "x"}, headers=device)
    assert resp.status_code == 403
    assert "notes:write" in resp.json()["detail"]
    async with memory_db.factory() as session:
        assert (await session.execute(select(NoteModel))).scalars().all() == []


async def test_a_scope_this_build_does_not_know_grants_nothing(client, memory_db):
    device = await _device(client)
    async with memory_db.factory() as session:
        await session.execute(update(DeviceModel).values(scopes=["admin"]))
        await session.commit()
    assert (await client.get("/notes", headers=device)).status_code == 403


async def test_pairing_grants_the_default_scopes(client, memory_db):
    await _device(client)
    async with memory_db.factory() as session:
        device = (await session.execute(select(DeviceModel))).scalar_one()
    assert device.scopes == ["read", "notes:write", "reviews:write"]


async def test_a_device_paired_on_0_18_2_keeps_its_notes_and_loses_the_rest(client, memory_db):
    await init_database(memory_db.engine)  # the shared template is built from the models
    await _migrate(memory_db.engine, BEFORE_SCOPES)
    token = "lum_paired-before-scopes"
    async with memory_db.engine.begin() as conn:
        columns = (await conn.execute(text("PRAGMA table_info(devices)"))).fetchall()
        assert "scopes" not in {c[1] for c in columns}
        # Raw SQL: at this revision the table has no scopes column.
        await conn.execute(
            text(
                "INSERT INTO devices (id, name, library, token_hash, created_at) "
                "VALUES ('old', 'old phone', 'default', :hash, '2026-11-01')"
            ),
            {"hash": devices.hash_secret(token)},
        )
    await init_database(memory_db.engine)
    device = {**PHONE, "Authorization": f"Bearer {token}"}

    assert (await client.get("/notes", headers=device)).status_code == 200
    created = await client.post("/notes", json={"content": "Still mine."}, headers=device)
    assert created.status_code == 201, created.text
    refused = await client.patch("/settings/llm", json={"engine_mode": "cloud"}, headers=device)
    assert refused.status_code == 403
    assert refused.json()["detail"] == LOCAL_ONLY


async def test_one_client_cannot_void_the_code_by_guessing(client):
    code = (await client.post("/devices/pairing-code")).json()["code"]
    for _ in range(devices._MAX_ATTEMPTS_PER_CLIENT):
        wrong = await client.post("/devices/pair", json={"code": "AAAA-AAAA", "name": "x"})
        assert wrong.status_code == 403
    limited = await client.post("/devices/pair", json={"code": "AAAA-AAAA", "name": "x"})
    assert limited.status_code == 429

    # The code survived: another address pairs with it.
    devices._attempts.clear()
    resp = await client.post("/devices/pair", json={"code": code, "name": "phone"})
    assert resp.status_code == 201, resp.text


async def test_the_attempt_window_reopens_after_a_code_lifetime(client, monkeypatch):
    for _ in range(devices._MAX_ATTEMPTS_PER_CLIENT):
        await client.post("/devices/pair", json={"code": "AAAA-AAAA", "name": "x"})
    later = devices.time.monotonic() + devices._CODE_TTL_S + 1
    monkeypatch.setattr(devices.time, "monotonic", lambda: later)
    code = (await client.post("/devices/pairing-code")).json()["code"]
    resp = await client.post("/devices/pair", json={"code": code, "name": "phone"})
    assert resp.status_code == 201, resp.text


def test_every_route_is_behind_the_device_check():
    # A route outside APIRoute (FastAPI's own docs were) never meets authorize_route.
    for route in app.routes:
        assert isinstance(route, APIRoute), f"{route.path} is not an API route"
        calls = {d.call for d in route.dependant.dependencies}
        assert authorize_route in calls, f"{route.path} skips authorize_route"


def _served(*, api_prefix: str = "", remote: bool = False, client=("127.0.0.1", 51000)):
    served = RequestAuthMiddleware(
        app,
        api_prefix=api_prefix,
        app_origins=frozenset(),
        pair_path="/devices/pair",
        remote_needs_token=remote,
    )
    return AsyncClient(transport=ASGITransport(app=served, client=client), base_url=OWN)


async def test_the_schema_answers_this_computer_and_a_reader(client, memory_db):
    assert (await client.get("/openapi.json")).status_code == 200
    device = await _device(client)
    assert (await client.get("/openapi.json", headers=device)).status_code == 200
    async with memory_db.factory() as session:
        await session.execute(update(DeviceModel).values(scopes=[]))
        await session.commit()
    assert (await client.get("/openapi.json", headers=device)).status_code == 403


@pytest.mark.parametrize("api_prefix", ["", "/api"])
async def test_the_schema_refuses_a_tokenless_caller_from_beyond(memory_db, api_prefix):
    # Public mode guards only /api, so the schema's root path is named to the middleware.
    async with _served(api_prefix=api_prefix, remote=True, client=("203.0.113.7", 1)) as c:
        assert (await c.get("/openapi.json")).status_code == 401
    async with _served(api_prefix=api_prefix) as c:
        assert (
            await c.get("/openapi.json", headers={"X-Forwarded-For": "203.0.113.7"})
        ).status_code == 401


async def test_the_api_docs_are_this_computers(client):
    assert (await client.get("/docs")).status_code == 200
    device = await _device(client)
    resp = await client.get("/docs", headers=device)
    assert resp.status_code == 403 and resp.json()["detail"] == LOCAL_ONLY
    assert any(
        d.call is require_this_computer
        for r in app.routes
        if isinstance(r, APIRoute) and r.path == "/docs"
        for d in r.dependant.dependencies
    )


async def test_a_forwarded_request_needs_a_token_with_remote_serving_off(client, memory_db):
    resp = await client.patch(
        "/settings", json={"planted": "yes"}, headers={"X-Forwarded-For": "203.0.113.7"}
    )
    assert resp.status_code == 401, resp.text
    assert (await client.get("/notes")).status_code == 200


@pytest.mark.parametrize("body", [{"model": "gpt-4o"}, {"web_enabled": True}])
async def test_a_device_cannot_choose_where_its_question_goes(client, monkeypatch, body):
    asked: list[object] = []

    class _QA:
        async def stream_answer(self, question, document_ids, scope, model, *_a, **_kw):
            asked.append(model)
            yield "data: done\n\n"

    monkeypatch.setattr(qa_router, "get_qa_service", lambda: _QA())
    device = await _device(client)

    refused = await client.post("/qa", json={"question": "q", **body}, headers=device)
    assert refused.status_code == 403, refused.text
    assert asked == []

    plain = await client.post("/qa", json={"question": "q"}, headers=device)
    assert plain.status_code == 200, plain.text
    assert asked == [None]
    # The app itself still picks its model.
    assert (await client.post("/qa", json={"question": "q", **body})).status_code == 200


def test_the_default_scopes_are_named_not_derived():
    # Aliased to DEVICE_SCOPES, every scope added later would reach every new pairing.
    assert DEFAULT_DEVICE_SCOPES == ("read", "notes:write", "reviews:write")
    assert set(DEFAULT_DEVICE_SCOPES) <= set(DEVICE_SCOPES)


def test_an_ipv6_client_is_its_64_and_a_mapped_v4_is_the_v4():
    key = devices._client_key
    assert key("2001:db8:1:2::a") == key("2001:db8:1:2:ffff::1") == "2001:db8:1:2::/64"
    assert key("2001:db8:1:3::a") != key("2001:db8:1:2::a")
    assert key("::ffff:192.0.2.1") == key("192.0.2.1") == "192.0.2.1"


def test_a_rotating_ipv6_host_shares_one_window():
    for i in range(devices._MAX_ATTEMPTS_PER_CLIENT):
        devices._count_attempt(f"2001:db8:1:2::{i + 1:x}")
    with pytest.raises(TooManyRequests):
        devices._count_attempt("2001:db8:1:2::ffff")


def test_a_full_table_forgets_the_least_recent_client_only(monkeypatch):
    monkeypatch.setattr(devices, "_MAX_TRACKED_CLIENTS", 3)
    for _ in range(devices._MAX_ATTEMPTS_PER_CLIENT):
        devices._count_attempt("192.0.2.1")
    devices._count_attempt("192.0.2.2")
    devices._count_attempt("192.0.2.3")
    devices._count_attempt("192.0.2.4")  # evicts .1, the least recently active

    assert set(devices._attempts) == {"192.0.2.2", "192.0.2.3", "192.0.2.4"}
    for _ in range(devices._MAX_ATTEMPTS_PER_CLIENT - 1):
        devices._count_attempt("192.0.2.2")
    with pytest.raises(TooManyRequests):
        devices._count_attempt("192.0.2.2")
