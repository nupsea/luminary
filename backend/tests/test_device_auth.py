"""Device auth and pairing: the 0.16.0 exit gate.

An unpaired origin or a revoked device is refused. Every test here that sends a foreign
`Origin` passes only while `RequestAuthMiddleware` is mounted and pairing works.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

import app.services.devices as devices
from app.main import app
from app.models import DeviceModel, SettingsModel
from app.runtime.request_auth import DEV_APP_ORIGINS, needs_token

OWN = "http://127.0.0.1:7820"
EVIL = {"Origin": "https://evil.example"}


@pytest.fixture(autouse=True)
def _no_active_code():
    devices._active_code = None
    yield
    devices._active_code = None


@pytest.fixture
async def client(memory_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=OWN) as c:
        yield c


async def _pair(client: AsyncClient, name: str = "phone") -> tuple[str, str]:
    code = (await client.post("/devices/pairing-code")).json()["code"]
    resp = await client.post("/devices/pair", json={"code": code, "name": name}, headers=EVIL)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["device_id"], body["token"]


async def test_an_unpaired_origin_cannot_write(client, memory_db):
    # A cross-site form POST needs no preflight; before 0.16.0 this ran.
    resp = await client.patch("/settings", json={"planted": "yes"}, headers=EVIL)

    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"
    async with memory_db.factory() as session:
        assert await session.get(SettingsModel, "planted") is None


async def test_a_null_origin_is_not_the_app(client):
    # Sandboxed iframes and file:// pages send the literal "null".
    resp = await client.get("/devices", headers={"Origin": "null"})
    assert resp.status_code == 401


async def test_a_cross_site_request_without_an_origin_is_refused(client):
    resp = await client.get("/tags", headers={"Sec-Fetch-Site": "cross-site"})
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {},  # the shell, smoke, evals: not a browser
        {"Origin": OWN},  # the SPA served by this backend
        {"Origin": "http://localhost:5173"},  # Vite in full mode
        {"Sec-Fetch-Site": "same-origin"},
        {"Sec-Fetch-Site": "none"},  # typed into the address bar
    ],
)
async def test_the_app_itself_needs_no_token(client, headers):
    resp = await client.get("/devices", headers=headers)
    assert resp.status_code == 200, resp.text


async def test_a_paired_device_is_admitted_until_revoked(client):
    device_id, token = await _pair(client)
    bearer = {**EVIL, "Authorization": f"Bearer {token}"}

    assert (await client.get("/tags", headers=bearer)).status_code == 200

    assert (await client.delete(f"/devices/{device_id}")).status_code == 204
    resp = await client.get("/tags", headers=bearer)
    assert resp.status_code == 401
    listed = (await client.get("/devices")).json()
    assert listed[0]["id"] == device_id and listed[0]["revoked_at"] is not None


async def test_a_device_cannot_manage_devices(client):
    _, token = await _pair(client)
    bearer = {"Authorization": f"Bearer {token}"}

    assert (await client.post("/devices/pairing-code", headers=bearer)).status_code == 403
    assert (await client.get("/devices", headers=bearer)).status_code == 403


@pytest.mark.parametrize("authorization", ["Bearer lum_not-a-token", "Basic abc", "Bearer "])
async def test_an_unknown_or_malformed_token_is_refused_even_from_the_app(client, authorization):
    resp = await client.get("/tags", headers={"Origin": OWN, "Authorization": authorization})
    assert resp.status_code == 401


async def test_only_the_tokens_hash_is_stored(client, memory_db):
    _, token = await _pair(client)
    async with memory_db.factory() as session:
        stored = (await session.execute(select(DeviceModel))).scalar_one()
        dump = "\n".join(str(r) for r in (await session.execute(text("SELECT * FROM devices"))))
    assert stored.token_hash == devices.hash_secret(token)
    assert token not in dump


async def test_a_pairing_code_pairs_once(client):
    code = (await client.post("/devices/pairing-code")).json()["code"]
    first = await client.post("/devices/pair", json={"code": code, "name": "a"}, headers=EVIL)
    second = await client.post("/devices/pair", json={"code": code, "name": "b"}, headers=EVIL)

    assert first.status_code == 201
    assert second.status_code == 403


async def test_the_code_is_read_forgivingly(client):
    code = (await client.post("/devices/pairing-code")).json()["code"]
    typed = code.replace("-", " ").lower()
    resp = await client.post("/devices/pair", json={"code": typed, "name": "a"}, headers=EVIL)
    assert resp.status_code == 201


async def test_five_wrong_guesses_void_the_code(client):
    code = (await client.post("/devices/pairing-code")).json()["code"]
    for _ in range(5):
        wrong = await client.post("/devices/pair", json={"code": "AAAA-AAAA", "name": "x"})
        assert wrong.status_code == 403
    resp = await client.post("/devices/pair", json={"code": code, "name": "x"})
    assert resp.status_code == 403


async def test_four_wrong_guesses_leave_the_code_usable(client):
    code = (await client.post("/devices/pairing-code")).json()["code"]
    for _ in range(4):
        await client.post("/devices/pair", json={"code": "AAAA-AAAA", "name": "x"})
    resp = await client.post("/devices/pair", json={"code": code, "name": "x"})
    assert resp.status_code == 201


async def test_an_expired_code_is_refused(client, monkeypatch):
    code = (await client.post("/devices/pairing-code")).json()["code"]
    later = devices.time.monotonic() + devices._CODE_TTL_S + 1
    monkeypatch.setattr(devices.time, "monotonic", lambda: later)

    resp = await client.post("/devices/pair", json={"code": code, "name": "x"})
    assert resp.status_code == 403


async def test_a_new_code_replaces_the_old_one(client):
    old = (await client.post("/devices/pairing-code")).json()["code"]
    await client.post("/devices/pairing-code")
    resp = await client.post("/devices/pair", json={"code": old, "name": "x"})
    assert resp.status_code == 403


async def test_revoking_an_unknown_device_is_404(client):
    assert (await client.delete("/devices/nope")).status_code == 404


def test_the_origin_rule():
    own = "http://127.0.0.1:7820"
    assert not needs_token(own, None, own, frozenset())
    assert not needs_token("http://localhost:5173", None, own, DEV_APP_ORIGINS)
    # Public mode trusts no dev server.
    assert needs_token("http://localhost:5173", None, own, frozenset())
    # Another port on loopback is another origin.
    assert needs_token("http://127.0.0.1:7821", None, own, frozenset())
    assert needs_token(None, "cross-site", own, frozenset())
    assert not needs_token(None, "same-site", own, frozenset())
    assert not needs_token(None, None, own, frozenset())
