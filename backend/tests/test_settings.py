"""Tests for LLM settings service — keychain storage, sentinel, migration, and routing."""

import keyring
import keyring.backend
import keyring.errors
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.settings_service as svc_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import SettingsModel
from app.services.settings_service import (
    _DEFAULTS,
    _KEYCHAIN_SENTINEL,
    decrypt_setting,
    encrypt_setting,
    get_effective_routing,
    get_llm_error_message,
    update_llm_settings,
)

# In-memory keyring backend for tests


class _InMemoryKeyring(keyring.backend.KeyringBackend):
    """Simple in-memory keyring backend — no OS interaction in tests."""

    priority = 100

    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}

    def set_password(self, service, username, password):
        self._store[(service, username)] = password

    def get_password(self, service, username):
        return self._store.get((service, username))

    def delete_password(self, service, username):
        key = (service, username)
        if key not in self._store:
            raise keyring.errors.PasswordDeleteError("not found")
        del self._store[key]


# Fixtures


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


@pytest.fixture(autouse=True)
def in_memory_keyring():
    """Replace the OS keyring with a clean in-memory backend for each test."""
    backend = _InMemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    # Reset to system default after test
    keyring.core._keyring_backend = None  # noqa: SLF001


# Tests


async def test_default_mode_is_private(test_db):
    """GET /settings/llm returns mode=private with no DB rows written."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        import unittest.mock

        with unittest.mock.patch(
            "app.routers.settings._fetch_ollama_models", return_value=(False, [])
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

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with unittest.mock.patch(
            "app.routers.settings._fetch_ollama_models", return_value=(False, [])
        ):
            resp = await client.patch(
                "/settings/llm",
                json={"mode": "cloud", "provider": "anthropic"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "cloud"
    assert data["provider"] == "anthropic"
    assert svc_module._cache["llm_mode"] == "cloud"
    assert svc_module._cache["cloud_provider"] == "anthropic"


async def test_patch_llm_settings_rejects_unknown_fields(test_db):
    """PATCH /settings/llm returns 422 for unknown field names (extra='forbid')."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            "/settings/llm",
            json={"mode": "cloud", "rogue_field": "x"},
        )
    assert resp.status_code == 422


async def test_openai_model_list_includes_gpt5_family(test_db):
    """The OpenAI model dropdown offers the latest GPT-5 models; cost-less entries
    are returned cleanly (name-only in the UI)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/settings/llm/models", params={"provider": "openai"})
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.json()]
    assert "gpt-5.4" in ids
    assert "gpt-5.1" in ids
    # gpt-4o-mini still present with its price metadata intact
    mini = next(m for m in resp.json() if m["id"] == "gpt-4o-mini")
    assert mini["cost_input"] == 0.15
    # a GPT-5 entry returns with no fabricated price
    g5 = next(m for m in resp.json() if m["id"] == "gpt-5.4")
    assert g5["cost_input"] is None


async def test_switch_to_gpt5_persists(test_db):
    """Selecting a GPT-5 model saves and is what the pipeline will resolve."""
    import unittest.mock

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with unittest.mock.patch(
            "app.routers.settings._fetch_ollama_models", return_value=(False, [])
        ):
            resp = await client.patch(
                "/settings/llm",
                json={"mode": "cloud", "provider": "openai", "model": "gpt-5.1"},
            )
    assert resp.status_code == 200
    assert svc_module._cache["cloud_model"] == "gpt-5.1"


async def test_api_key_stored_as_keychain_sentinel(test_db, in_memory_keyring):
    """set() writes '__keychain__' sentinel to SQLite; get() returns original value."""
    engine, factory = test_db
    raw_key = "sk-test-plaintext-secret"

    async with factory() as session:
        await update_llm_settings(session, openai_api_key=raw_key)

    # SQLite row must contain the sentinel, not the raw key
    async with factory() as session:
        result = await session.execute(
            select(SettingsModel).where(SettingsModel.key == "openai_api_key")
        )
        row = result.scalar_one()
        assert row.value == _KEYCHAIN_SENTINEL, f"SQLite stored {row.value!r} instead of sentinel"

    # Keychain holds the raw value
    stored_in_keychain = in_memory_keyring.get_password("luminary", "openai_api_key")
    assert stored_in_keychain == raw_key

    # Cache holds the raw value (used by get_effective_routing)
    assert svc_module._cache["openai_api_key"] == raw_key


async def test_load_resolves_keychain_sentinel(test_db, in_memory_keyring):
    """load_llm_settings() fetches the actual key from keychain when sentinel is stored."""
    engine, factory = test_db
    raw_key = "sk-resolved-from-keychain"

    # Pre-populate keychain and write sentinel directly to SQLite
    in_memory_keyring.set_password("luminary", "openai_api_key", raw_key)
    async with factory() as session:
        session.add(SettingsModel(key="openai_api_key", value=_KEYCHAIN_SENTINEL))
        await session.commit()

    # Reset cache to simulate a fresh load
    svc_module._cache.update(_DEFAULTS)

    async with factory() as session:
        from app.services.settings_service import load_llm_settings

        await load_llm_settings(session)

    assert svc_module._cache["openai_api_key"] == raw_key


async def test_legacy_xor_key_migrated_on_load(test_db, in_memory_keyring):
    """Existing XOR-encrypted DB entries are auto-migrated to keychain on first load."""
    engine, factory = test_db
    raw_key = "sk-old-xor-encrypted"
    xor_hex = encrypt_setting(raw_key)

    # Simulate old DB with XOR-encrypted value
    async with factory() as session:
        session.add(SettingsModel(key="openai_api_key", value=xor_hex))
        await session.commit()

    # Reset cache
    svc_module._cache.update(_DEFAULTS)

    async with factory() as session:
        from app.services.settings_service import load_llm_settings

        await load_llm_settings(session)

    # Cache should hold the raw key after migration
    assert svc_module._cache["openai_api_key"] == raw_key

    # SQLite should now have the sentinel
    async with factory() as session:
        result = await session.execute(
            select(SettingsModel).where(SettingsModel.key == "openai_api_key")
        )
        row = result.scalar_one()
        assert row.value == _KEYCHAIN_SENTINEL

    # Keychain should hold the raw key
    assert in_memory_keyring.get_password("luminary", "openai_api_key") == raw_key


async def test_has_key_boolean_true_after_save(test_db):
    """GET /settings/llm reflects has_openai_key=True after saving a key."""
    import unittest.mock

    engine, factory = test_db
    async with factory() as session:
        await update_llm_settings(session, openai_api_key="sk-test-key-12345")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with unittest.mock.patch(
            "app.routers.settings._fetch_ollama_models", return_value=(False, [])
        ):
            resp = await client.get("/settings/llm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_openai_key"] is True


async def test_clear_key_removes_from_keychain(test_db, in_memory_keyring):
    """Passing empty string clears key from keychain and writes empty string to SQLite."""
    engine, factory = test_db
    async with factory() as session:
        await update_llm_settings(session, openai_api_key="sk-to-delete")

    async with factory() as session:
        await update_llm_settings(session, openai_api_key="")

    assert svc_module._cache["openai_api_key"] == ""
    assert in_memory_keyring.get_password("luminary", "openai_api_key") is None

    async with factory() as session:
        result = await session.execute(
            select(SettingsModel).where(SettingsModel.key == "openai_api_key")
        )
        row = result.scalar_one()
        assert row.value == ""


async def test_stale_sentinel_missing_from_keychain(test_db):
    """Sentinel in SQLite but no keychain entry -> cache falls back to empty string."""
    engine, factory = test_db

    async with factory() as session:
        session.add(SettingsModel(key="openai_api_key", value=_KEYCHAIN_SENTINEL))
        await session.commit()

    svc_module._cache.update(_DEFAULTS)

    async with factory() as session:
        from app.services.settings_service import load_llm_settings

        await load_llm_settings(session)

    assert svc_module._cache["openai_api_key"] == ""


async def test_unknown_format_key_loaded_with_warning(test_db, caplog):
    """Non-sentinel, non-empty, non-hex DB value loads as-is with a warning logged."""
    import logging

    engine, factory = test_db
    raw_value = "plaintext-not-hex!"

    async with factory() as session:
        session.add(SettingsModel(key="openai_api_key", value=raw_value))
        await session.commit()

    svc_module._cache.update(_DEFAULTS)

    with caplog.at_level(logging.WARNING, logger="app.services.settings_service"):
        async with factory() as session:
            from app.services.settings_service import load_llm_settings

            await load_llm_settings(session)

    assert svc_module._cache["openai_api_key"] == raw_value
    assert any("unexpected DB format" in r.message for r in caplog.records)


async def test_cloud_mode_raises_when_no_key(test_db, monkeypatch):
    """get_effective_routing raises ValueError only when neither the keychain nor
    the .env key is present."""
    from types import SimpleNamespace

    import app.config as config_module

    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: SimpleNamespace(OPENAI_API_KEY="", ANTHROPIC_API_KEY="", GOOGLE_API_KEY=""),
    )
    svc_module._cache.update(
        {"llm_mode": "cloud", "cloud_provider": "openai", "openai_api_key": ""}
    )

    with pytest.raises(ValueError, match="key not configured"):
        get_effective_routing()


async def test_cloud_mode_falls_back_to_env_key(test_db, monkeypatch):
    """When the app keychain has no key, the .env key is used — so mode-based
    'Auto' chat behaves consistently with explicit overrides and evals."""
    from types import SimpleNamespace

    import app.config as config_module

    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: SimpleNamespace(
            OPENAI_API_KEY="sk-env-fallback", ANTHROPIC_API_KEY="", GOOGLE_API_KEY=""
        ),
    )
    svc_module._cache.update(
        {
            "llm_mode": "cloud",
            "cloud_provider": "openai",
            "cloud_model": "gpt-5.1",
            "openai_api_key": "",  # keychain empty
        }
    )

    model_str, api_key = get_effective_routing()
    assert model_str == "openai/gpt-5.1"
    assert api_key == "sk-env-fallback"


async def test_keychain_key_preferred_over_env(test_db, monkeypatch):
    """A key set in the app (keychain) takes precedence over the .env key."""
    from types import SimpleNamespace

    import app.config as config_module

    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: SimpleNamespace(
            OPENAI_API_KEY="sk-env", ANTHROPIC_API_KEY="", GOOGLE_API_KEY=""
        ),
    )
    svc_module._cache.update(
        {
            "llm_mode": "cloud",
            "cloud_provider": "openai",
            "cloud_model": "gpt-4o",
            "openai_api_key": "sk-keychain",
        }
    )

    _model_str, api_key = get_effective_routing()
    assert api_key == "sk-keychain"


async def test_cloud_mode_returns_raw_key(test_db):
    """get_effective_routing returns the raw API key directly (no XOR decrypt needed)."""
    raw_key = "sk-live-key-xyz"
    svc_module._cache.update(
        {
            "llm_mode": "cloud",
            "cloud_provider": "openai",
            "cloud_model": "gpt-4o",
            "openai_api_key": raw_key,
        }
    )

    model_str, api_key = get_effective_routing()
    assert model_str == "openai/gpt-4o"
    assert api_key == raw_key


def test_encrypt_decrypt_roundtrip():
    """encrypt_setting/decrypt_setting are symmetric (kept for legacy migration)."""
    original = "my-secret-key-abc123"
    assert decrypt_setting(encrypt_setting(original)) == original


def test_encrypt_returns_hex_not_plaintext():
    """encrypt_setting does not return plaintext (kept for legacy migration)."""
    original = "super-secret"
    encrypted = encrypt_setting(original)
    assert encrypted != original
    bytes.fromhex(encrypted)


@pytest.fixture
def restore_mode():
    original = svc_module._cache.get("llm_mode", "private")
    yield
    svc_module._cache["llm_mode"] = original


def test_llm_error_message_private_mentions_ollama(restore_mode):
    svc_module._cache["llm_mode"] = "private"
    assert "ollama serve" in get_llm_error_message()


def test_llm_error_message_hybrid_mentions_keys_and_ollama(restore_mode):
    svc_module._cache["llm_mode"] = "hybrid"
    msg = get_llm_error_message()
    assert "API key" in msg
    assert "Ollama" in msg


def test_llm_error_message_cloud_mentions_keys_not_ollama(restore_mode):
    svc_module._cache["llm_mode"] = "cloud"
    msg = get_llm_error_message()
    assert "API key" in msg
    assert "Ollama" not in msg


def test_llm_error_message_defaults_to_private_when_unset(restore_mode):
    svc_module._cache.pop("llm_mode", None)
    assert "ollama serve" in get_llm_error_message()
