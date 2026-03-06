"""Tests for S74 — GET/PATCH /settings/llm, XOR encryption, and routing."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.settings_service as svc_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.services.settings_service import (
    _DEFAULTS,
    decrypt_setting,
    encrypt_setting,
    get_effective_routing,
    update_llm_settings,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    # Reset module-level cache to defaults before each test
    svc_module._cache.update(_DEFAULTS)

    yield engine, factory

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()

    # Restore cache to defaults after test
    svc_module._cache.update(_DEFAULTS)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_default_mode_is_private(test_db):
    """GET /settings/llm returns mode=private with no DB rows written."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Mock Ollama to avoid network call
        import unittest.mock

        with unittest.mock.patch(
            "app.routers.settings._fetch_ollama_models", return_value=[]
        ):
            resp = await client.get("/settings/llm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "private"
    assert data["has_openai_key"] is False
    assert data["has_anthropic_key"] is False
    assert data["has_google_key"] is False


async def test_patch_llm_settings_persists_mode(test_db):
    """PATCH /settings/llm persists mode and provider changes."""
    import unittest.mock

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        with unittest.mock.patch(
            "app.routers.settings._fetch_ollama_models", return_value=[]
        ):
            resp = await client.patch(
                "/settings/llm",
                json={"mode": "cloud", "provider": "anthropic"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "cloud"
    assert data["provider"] == "anthropic"
    # Module-level cache should reflect the change
    assert svc_module._cache["llm_mode"] == "cloud"
    assert svc_module._cache["cloud_provider"] == "anthropic"


async def test_api_key_stored_encrypted_not_plaintext(test_db):
    """Saving an API key encrypts it; raw plaintext must not appear in the DB."""
    engine, factory = test_db
    raw_key = "sk-test-plaintext-secret"

    async with factory() as session:
        await update_llm_settings(session, openai_api_key=raw_key)

    # Verify the cache holds the encrypted version, not plaintext
    stored = svc_module._cache["openai_api_key"]
    assert stored != raw_key, "Key was stored as plaintext"
    assert stored != "", "Key was not stored at all"

    # Verify decrypt round-trips correctly
    assert decrypt_setting(stored) == raw_key


async def test_has_key_boolean_true_after_save(test_db):
    """GET /settings/llm reflects has_openai_key=True after saving a key."""
    import unittest.mock

    # First set a key directly in the service
    engine, factory = test_db
    async with factory() as session:
        await update_llm_settings(session, openai_api_key="sk-test-key-12345")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        with unittest.mock.patch(
            "app.routers.settings._fetch_ollama_models", return_value=[]
        ):
            resp = await client.get("/settings/llm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_openai_key"] is True


async def test_cloud_mode_raises_when_no_key(test_db):
    """get_effective_routing raises ValueError when cloud mode + missing key."""
    # Set cloud mode with no key
    svc_module._cache.update(
        {"llm_mode": "cloud", "cloud_provider": "openai", "openai_api_key": ""}
    )

    with pytest.raises(ValueError, match="key not configured"):
        get_effective_routing()


def test_encrypt_decrypt_roundtrip():
    """encrypt_setting/decrypt_setting are symmetric."""
    original = "my-secret-key-abc123"
    assert decrypt_setting(encrypt_setting(original)) == original


def test_encrypt_returns_hex_not_plaintext():
    """encrypt_setting does not return plaintext."""
    original = "super-secret"
    encrypted = encrypt_setting(original)
    assert encrypted != original
    # Valid hex string
    bytes.fromhex(encrypted)
