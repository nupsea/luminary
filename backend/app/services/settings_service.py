"""LLM settings service — DB-backed mode/provider/key management with OS keychain storage."""

import hashlib
import logging
import socket

import keyring
import keyring.errors
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SettingsModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keychain constants
# ---------------------------------------------------------------------------

_KEYCHAIN_SERVICE = "luminary"
_KEYCHAIN_SENTINEL = "__keychain__"

# ---------------------------------------------------------------------------
# XOR encryption — kept for migration of pre-keychain DB entries only
# ---------------------------------------------------------------------------

_XOR_KEY: bytes = hashlib.sha256(socket.gethostname().encode()).digest()

_LLM_SETTING_KEYS = (
    "llm_mode",
    "cloud_provider",
    "cloud_model",
    "openai_api_key",
    "anthropic_api_key",
    "google_api_key",
)

_API_KEY_FIELDS = frozenset({"openai_api_key", "anthropic_api_key", "google_api_key"})

_DEFAULTS: dict[str, str] = {
    "llm_mode": "private",
    "cloud_provider": "openai",
    "cloud_model": "gpt-4o-mini",
    "openai_api_key": "",
    "anthropic_api_key": "",
    "google_api_key": "",
}

# Module-level mutable cache — populated on startup and updated on PATCH.
# API key fields store the raw (decrypted) value; non-key fields store as-is.
_cache: dict[str, str] = dict(_DEFAULTS)


def encrypt_setting(value: str) -> str:
    """XOR-encrypt a string value; returns a hex string. Kept for legacy migration only."""
    b = value.encode()
    return bytes([b[i] ^ _XOR_KEY[i % len(_XOR_KEY)] for i in range(len(b))]).hex()


def decrypt_setting(encrypted: str) -> str:
    """Decrypt a hex string previously encrypted by encrypt_setting.

    Kept for legacy migration only.
    """
    b = bytes.fromhex(encrypted)
    return bytes([b[i] ^ _XOR_KEY[i % len(_XOR_KEY)] for i in range(len(b))]).decode()


def _is_xor_encrypted(value: str) -> bool:
    """Return True if value looks like an old XOR-encrypted hex string.

    Old XOR values are even-length strings containing only hex characters.
    """
    if not value or value == _KEYCHAIN_SENTINEL:
        return False
    if len(value) % 2 != 0:
        return False
    try:
        bytes.fromhex(value)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# DB CRUD
# ---------------------------------------------------------------------------


async def load_llm_settings(db: AsyncSession) -> None:
    """Load LLM settings from DB into module-level cache.

    For API key fields: resolves the keychain sentinel to the raw value, and
    auto-migrates legacy XOR-encrypted values to the OS keychain on first read.
    """
    for key in _LLM_SETTING_KEYS:
        result = await db.execute(select(SettingsModel).where(SettingsModel.key == key))
        row = result.scalar_one_or_none()
        if row is None:
            continue

        raw_value = str(row.value)

        if key not in _API_KEY_FIELDS:
            _cache[key] = raw_value
            continue

        # API key field: resolve sentinel or migrate legacy XOR value
        if raw_value == _KEYCHAIN_SENTINEL:
            retrieved = keyring.get_password(_KEYCHAIN_SERVICE, key)
            _cache[key] = retrieved or ""
        elif raw_value == "":
            _cache[key] = ""
        elif _is_xor_encrypted(raw_value):
            # Legacy XOR-encrypted entry — migrate to OS keychain automatically
            try:
                plaintext = decrypt_setting(raw_value)
            except Exception:
                logger.warning("Failed to decrypt legacy key %r -- clearing it", key)
                _cache[key] = ""
                continue
            keyring.set_password(_KEYCHAIN_SERVICE, key, plaintext)
            sentinel_row = SettingsModel(key=key, value=_KEYCHAIN_SENTINEL)
            await db.merge(sentinel_row)
            await db.commit()
            _cache[key] = plaintext
            logger.debug("Migrated legacy XOR key %r to OS keychain", key)
        else:
            # Unknown format — should not happen in normal operation since
            # update_llm_settings always writes sentinel or empty string.
            # Log a warning so this is visible in monitoring if it occurs.
            logger.warning(
                "API key field %r has unexpected DB format (not sentinel/empty/XOR); "
                "treating as raw value. If this persists, re-save the key in Settings.",
                key,
            )
            _cache[key] = raw_value


async def get_llm_settings(db: AsyncSession) -> dict:
    """Return current LLM settings (with has_*_key booleans, no raw key values)."""
    await load_llm_settings(db)
    return {
        "mode": _cache["llm_mode"],
        "provider": _cache["cloud_provider"],
        "model": _cache["cloud_model"],
        "has_openai_key": bool(_cache["openai_api_key"]),
        "has_anthropic_key": bool(_cache["anthropic_api_key"]),
        "has_google_key": bool(_cache["google_api_key"]),
    }


async def update_llm_settings(
    db: AsyncSession,
    *,
    mode: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    openai_api_key: str | None = None,
    anthropic_api_key: str | None = None,
    google_api_key: str | None = None,
) -> None:
    """Save LLM settings to DB and refresh module-level cache.

    Passing ``None`` for a field means 'do not change'.
    Passing an empty string for a key field means 'clear this key'.

    API keys are stored in the OS keychain; the sentinel '__keychain__' is
    written to SQLite so no raw key ever appears in the database.
    """
    updates_db: dict[str, str] = {}
    updates_cache: dict[str, str] = {}

    if mode is not None:
        updates_db["llm_mode"] = mode
        updates_cache["llm_mode"] = mode
    if provider is not None:
        updates_db["cloud_provider"] = provider
        updates_cache["cloud_provider"] = provider
    if model is not None:
        updates_db["cloud_model"] = model
        updates_cache["cloud_model"] = model

    key_args = {
        "openai_api_key": openai_api_key,
        "anthropic_api_key": anthropic_api_key,
        "google_api_key": google_api_key,
    }
    for field, raw_value in key_args.items():
        if raw_value is None:
            continue
        if raw_value:
            keyring.set_password(_KEYCHAIN_SERVICE, field, raw_value)
            updates_db[field] = _KEYCHAIN_SENTINEL
            updates_cache[field] = raw_value
        else:
            # Clear key from keychain and DB
            try:
                keyring.delete_password(_KEYCHAIN_SERVICE, field)
            except keyring.errors.PasswordDeleteError:
                pass
            updates_db[field] = ""
            updates_cache[field] = ""

    for key, value in updates_db.items():
        setting = SettingsModel(key=key, value=value)
        await db.merge(setting)
    await db.commit()
    _cache.update(updates_cache)
    logger.debug("LLM settings updated: %s", list(updates_db.keys()))


# ---------------------------------------------------------------------------
# Routing helper — used by LLMService
# ---------------------------------------------------------------------------


def get_effective_routing() -> tuple[str, str | None]:
    """Return (litellm_model_string, api_key_or_none).

    Raises ValueError when cloud mode is active but the corresponding API key
    is not configured. Callers should convert this to HTTP 503.
    """
    if _cache["llm_mode"] == "private":
        from app.config import get_settings  # noqa: PLC0415

        ollama_model = get_settings().LITELLM_DEFAULT_MODEL
        if not ollama_model.startswith("ollama/"):
            ollama_model = f"ollama/{ollama_model}"
        return ollama_model, None

    provider = _cache["cloud_provider"]
    cloud_model = _cache["cloud_model"]

    _provider_map: dict[str, tuple[str, str]] = {
        "openai": ("openai", "openai_api_key"),
        "anthropic": ("anthropic", "anthropic_api_key"),
        "gemini": ("gemini", "google_api_key"),
    }
    prefix, key_field = _provider_map.get(provider, ("openai", "openai_api_key"))
    api_key = _cache[key_field]  # raw value — no decrypt needed

    if not api_key:
        raise ValueError(
            f"Cloud LLM key not configured for {provider}. "
            "Go to Settings to add your API key."
        )

    return f"{prefix}/{cloud_model}", api_key
