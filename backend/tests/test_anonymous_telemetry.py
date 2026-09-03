"""Tests for anonymous product telemetry (TelemetryDeck v2 compatibility and privacy)."""

import os
import uuid
from pathlib import Path

import httpx
import pytest

from app.services.anonymous_telemetry import (
    _scrub_payload,
    _scrub_value,
    check_and_mark_first_run,
    detect_distribution,
    get_telemetry_client_id,
    is_telemetry_opted_out,
    record_startup_telemetry,
    send_signal,
    set_telemetry_enabled,
)


@pytest.fixture(autouse=True)
def clean_telemetry_state(tmp_path, monkeypatch):
    """Ensure clean data directory and reset module-level caches for each test."""
    data_dir = tmp_path / ".luminary"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Point DATA_DIR to tmp_path
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(settings, "TELEMETRY_ENABLED", True)
    monkeypatch.setattr(settings, "TELEMETRY_APP_ID", "TEST-APP-ID")

    # Clear env vars
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.delenv("LUMINARY_TELEMETRY", raising=False)
    monkeypatch.delenv("LUMINARY_TELEMETRY_DISABLED", raising=False)
    monkeypatch.delenv("LUMINARY_TELEMETRY_APP_ID", raising=False)
    monkeypatch.delenv("LUMINARY_INSTALL_SOURCE", raising=False)
    monkeypatch.delenv("LUMINARY_CONTAINER", raising=False)

    import app.services.anonymous_telemetry as tm

    monkeypatch.setattr(tm, "_in_memory_enabled", None)
    monkeypatch.setattr(tm, "_cached_client_id", None)

    # Telemetry is refused outright in private mode, and `private` is the
    # default, so every test that exercises the ENABLED path has to say which
    # mode it is in. Stated here rather than hidden, because it is the single
    # biggest thing that turns telemetry off in the field.
    from app.services import settings_service

    monkeypatch.setitem(settings_service._cache, "llm_mode", "hybrid")

    yield data_dir


def test_client_id_generation_and_persistence(clean_telemetry_state):
    """Generates a valid UUID v4 and persists it across calls."""
    cid1 = get_telemetry_client_id()
    assert cid1 is not None
    # Validate format
    parsed_uuid = uuid.UUID(cid1)
    assert parsed_uuid.version == 4

    # File should exist
    id_file = clean_telemetry_state / ".telemetry_id"
    assert id_file.is_file()
    assert id_file.read_text().strip() == cid1

    # Second call returns same client ID
    cid2 = get_telemetry_client_id()
    assert cid1 == cid2


def test_first_run_detection(clean_telemetry_state):
    """Detects initial launch vs subsequent runs."""
    install_file = clean_telemetry_state / ".install_id"
    assert not install_file.exists()

    assert check_and_mark_first_run() is True
    assert install_file.is_file()

    # Second run is no longer first run
    assert check_and_mark_first_run() is False


def test_telemetry_opt_out_env_vars(monkeypatch):
    """DO_NOT_TRACK and LUMINARY_TELEMETRY=0 disable telemetry."""
    assert is_telemetry_opted_out() is False

    monkeypatch.setenv("DO_NOT_TRACK", "1")
    assert is_telemetry_opted_out() is True

    monkeypatch.delenv("DO_NOT_TRACK")
    monkeypatch.setenv("LUMINARY_TELEMETRY", "0")
    assert is_telemetry_opted_out() is True

    monkeypatch.delenv("LUMINARY_TELEMETRY")
    monkeypatch.setenv("LUMINARY_TELEMETRY_DISABLED", "true")
    assert is_telemetry_opted_out() is True


def test_telemetry_toggle_preference(clean_telemetry_state):
    """Dynamic opt-out via set_telemetry_enabled persists preference."""
    assert is_telemetry_opted_out() is False

    set_telemetry_enabled(False)
    assert is_telemetry_opted_out() is True
    assert (clean_telemetry_state / ".telemetry_opt_out").exists()

    set_telemetry_enabled(True)
    assert is_telemetry_opted_out() is False
    assert not (clean_telemetry_state / ".telemetry_opt_out").exists()


def test_scrub_paths_and_usernames(monkeypatch):
    """Scrubbing ensures local home paths and usernames are redacted."""
    home_dir = str(Path.home())
    username = os.path.basename(home_dir)

    raw_path = f"{home_dir}/projects/secret_doc.pdf"
    clean_val = _scrub_value(raw_path)
    assert home_dir not in clean_val
    assert clean_val.startswith("~/projects")

    payload = {
        "file": raw_path,
        "author": username,
        "count": 42,
        "active": True,
    }
    scrubbed = _scrub_payload(payload)
    assert home_dir not in scrubbed["file"]
    if len(username) >= 3:
        assert username not in scrubbed["author"]
    assert scrubbed["count"] == 42
    assert scrubbed["active"] is True


def test_distribution_detection(monkeypatch):
    """Correctly identifies packaged macOS app, Docker, Linux, Windows."""
    # 1. Packaged macOS
    monkeypatch.setattr("app.services.anonymous_telemetry.is_packaged", lambda: True)
    assert detect_distribution() == "macos_dmg"

    # 2. Docker
    monkeypatch.setattr("app.services.anonymous_telemetry.is_packaged", lambda: False)
    monkeypatch.setenv("LUMINARY_CONTAINER", "1")
    assert detect_distribution() == "docker"

    # 3. Explicit override
    monkeypatch.setenv("LUMINARY_INSTALL_SOURCE", "custom_dist")
    assert detect_distribution() == "custom_dist"


@pytest.mark.asyncio
async def test_send_signal_telemetrydeck_format(monkeypatch):
    """Validates TelemetryDeck v2 JSON array payload."""
    sent_request = {}

    async def mock_post(self, url, json=None, headers=None, **kwargs):
        sent_request["url"] = str(url)
        sent_request["json"] = json
        sent_request["headers"] = headers
        return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    success = await send_signal("install.first_run", {"custom_prop": "value"}, float_value=1.0)
    assert success is True

    body = sent_request["json"]
    assert isinstance(body, list)
    assert len(body) == 1

    event = body[0]
    assert event["appID"] == "TEST-APP-ID"
    assert event["type"] == "install.first_run"
    assert event["floatValue"] == 1.0
    assert event["clientUser"] is not None

    payload = event["payload"]
    assert payload["custom_prop"] == "value"
    assert "os" in payload
    assert "arch" in payload
    assert "luminary_version" in payload
    assert "distribution" in payload


@pytest.mark.asyncio
async def test_send_signal_offline_silent_resilience(monkeypatch):
    """Network failure or timeout does not raise and returns False."""
    async def mock_post(*args, **kwargs):
        raise httpx.ConnectTimeout("Network unreachable")

    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    success = await send_signal("app.start")
    assert success is False


@pytest.mark.asyncio
async def test_send_signal_opted_out_does_nothing(monkeypatch):
    """When opted out, zero network calls are made."""
    monkeypatch.setenv("DO_NOT_TRACK", "1")

    post_called = False

    async def mock_post(*args, **kwargs):
        nonlocal post_called
        post_called = True
        return httpx.Response(200)

    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    success = await send_signal("app.start")
    assert success is False
    assert post_called is False


@pytest.mark.asyncio
async def test_record_startup_telemetry(monkeypatch):
    """Startup telemetry fires install.first_run on first launch and app.start."""
    signals_sent = []

    async def mock_send(signal_type, payload=None, float_value=None):
        signals_sent.append(signal_type)
        return True

    monkeypatch.setattr("app.services.anonymous_telemetry.send_signal", mock_send)

    # First launch
    await record_startup_telemetry()
    assert "install.first_run" in signals_sent
    assert "app.start" in signals_sent

    signals_sent.clear()
    # Second launch
    await record_startup_telemetry()
    assert "install.first_run" not in signals_sent
    assert "app.start" in signals_sent


@pytest.mark.asyncio
async def test_telemetry_settings_api(clean_telemetry_state):
    """GET and PATCH /settings/telemetry work as expected."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. GET initial
        resp = await client.get("/settings/telemetry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["client_id"] is not None
        assert data["app_id"] == "TEST-APP-ID"

        # 2. PATCH disable
        patch_resp = await client.patch("/settings/telemetry", json={"enabled": False})
        assert patch_resp.status_code == 200
        assert patch_resp.json()["enabled"] is False

        # 3. Verify GET reflects disabled
        get_resp2 = await client.get("/settings/telemetry")
        assert get_resp2.json()["enabled"] is False

        # 4. PATCH re-enable and update app_id
        patch_resp2 = await client.patch(
            "/settings/telemetry", json={"enabled": True, "app_id": "NEW-CUSTOM-APP-ID"}
        )
        assert patch_resp2.status_code == 200
        assert patch_resp2.json()["enabled"] is True
        assert patch_resp2.json()["app_id"] == "NEW-CUSTOM-APP-ID"
        assert patch_resp2.json()["telemetrydeck_configured"] is True


@pytest.mark.asyncio
async def test_local_telemetry_and_monitoring_endpoints(clean_telemetry_state):
    """Local event store aggregates signals and serves them via /monitoring/telemetry."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.services.anonymous_telemetry import get_local_telemetry_stats

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Ingest an install event via the backend endpoint
        ingest_resp = await client.post(
            "/monitoring/telemetry/event",
            json={
                "signal_type": "install.linux.completed",
                "payload": {"distribution": "linux_source", "duration_seconds": 120.0},
                "float_value": 120.0,
            },
        )
        assert ingest_resp.status_code == 200
        assert ingest_resp.json()["status"] == "recorded"

        # Verify local stats updated
        stats = get_local_telemetry_stats()
        assert stats["installs_total"] >= 1
        assert stats["by_distribution"].get("linux_source", 0) >= 1
        assert len(stats["recent_events"]) >= 1

        # Check GET /monitoring/telemetry returns the overview with local_stats
        mon_resp = await client.get("/monitoring/telemetry")
        assert mon_resp.status_code == 200
        mon_data = mon_resp.json()
        assert "local_stats" in mon_data
        assert mon_data["local_stats"]["installs_total"] >= 1
        assert "platform_metadata" in mon_data




def test_private_mode_refuses_telemetry(monkeypatch):
    """Private mode sends nothing off the machine, and that outranks every setting.

    README states it without qualification, and a user who chose private mode
    chose it for exactly this reason -- so it beats an explicit opt-in, not just
    the default.
    """
    from app.services import settings_service

    monkeypatch.setitem(settings_service._cache, "llm_mode", "private")
    set_telemetry_enabled(True)

    assert is_telemetry_opted_out() is True


def test_private_mode_is_the_failure_default(monkeypatch):
    """An unloaded settings cache must fail closed, not open."""
    from app.services import settings_service

    monkeypatch.setattr(settings_service, "_cache", {}, raising=False)

    assert is_telemetry_opted_out() is True


@pytest.mark.parametrize("mode", ["hybrid", "cloud"])
def test_other_modes_still_allow_telemetry(mode, monkeypatch):
    from app.services import settings_service

    monkeypatch.setitem(settings_service._cache, "llm_mode", mode)
    set_telemetry_enabled(True)

    assert is_telemetry_opted_out() is False
