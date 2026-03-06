"""LLM settings service — DB-backed mode/provider/key management with XOR encryption."""

import hashlib
import logging
import socket

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SettingsModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# XOR encryption — prevents casual plaintext in DB (not adversarial-grade)
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

_DEFAULTS: dict[str, str] = {
    "llm_mode": "private",
    "cloud_provider": "openai",
    "cloud_model": "gpt-4o-mini",
    "openai_api_key": "",
    "anthropic_api_key": "",
    "google_api_key": "",
}

# Module-level mutable cache — populated on startup and updated on PATCH
_cache: dict[str, str] = dict(_DEFAULTS)


def encrypt_setting(value: str) -> str:
    """XOR-encrypt a string value; returns a hex string."""
    b = value.encode()
    return bytes([b[i] ^ _XOR_KEY[i % len(_XOR_KEY)] for i in range(len(b))]).hex()


def decrypt_setting(encrypted: str) -> str:
    """Decrypt a hex string previously encrypted by encrypt_setting."""
    b = bytes.fromhex(encrypted)
    return bytes([b[i] ^ _XOR_KEY[i % len(_XOR_KEY)] for i in range(len(b))]).decode()


# ---------------------------------------------------------------------------
# DB CRUD
# ---------------------------------------------------------------------------


async def load_llm_settings(db: AsyncSession) -> None:
    """Load LLM settings from DB into module-level cache."""
    for key in _LLM_SETTING_KEYS:
        result = await db.execute(
            select(SettingsModel).where(SettingsModel.key == key)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            _cache[key] = str(row.value)


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
    """
    updates: dict[str, str] = {}
    if mode is not None:
        updates["llm_mode"] = mode
    if provider is not None:
        updates["cloud_provider"] = provider
    if model is not None:
        updates["cloud_model"] = model
    if openai_api_key is not None:
        updates["openai_api_key"] = encrypt_setting(openai_api_key) if openai_api_key else ""
    if anthropic_api_key is not None:
        updates["anthropic_api_key"] = (
            encrypt_setting(anthropic_api_key) if anthropic_api_key else ""
        )
    if google_api_key is not None:
        updates["google_api_key"] = encrypt_setting(google_api_key) if google_api_key else ""

    for key, value in updates.items():
        setting = SettingsModel(key=key, value=value)
        await db.merge(setting)
    await db.commit()
    _cache.update(updates)
    logger.debug("LLM settings updated: %s", list(updates.keys()))


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
    encrypted_key = _cache[key_field]

    if not encrypted_key:
        raise ValueError(
            f"Cloud LLM key not configured for {provider}. "
            "Go to Settings to add your API key."
        )

    api_key = decrypt_setting(encrypted_key)
    return f"{prefix}/{cloud_model}", api_key
