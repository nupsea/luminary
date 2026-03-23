"""Settings router — GET and PATCH /settings/llm (DB-backed, mode + encrypted keys)."""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.services.settings_service import get_llm_settings, update_llm_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

_OLLAMA_TIMEOUT = 3.0


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class LLMSettingsResponse(BaseModel):
    # DB-backed new fields
    mode: str
    provider: str
    model: str
    has_openai_key: bool
    has_anthropic_key: bool
    has_google_key: bool
    # Backward-compat fields (for Monitoring.tsx and legacy consumers)
    processing_mode: str = "unavailable"
    active_model: str = ""
    available_local_models: list[str] = []
    cloud_providers: list[Any] = []


class LLMSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str | None = None
    provider: str | None = None
    model: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fetch_ollama_models(ollama_url: str) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT) as client:
            resp = await client.get(f"{ollama_url}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                return [f"ollama/{m['name']}" for m in data.get("models", [])]
    except Exception:
        pass
    return []


async def _build_response(data: dict, ollama_url: str) -> LLMSettingsResponse:
    """Merge new DB fields with backward-compat Ollama-derived fields."""
    available_local_models = await _fetch_ollama_models(ollama_url)

    if data["mode"] == "private":
        processing_mode = "local" if available_local_models else "unavailable"
    else:
        processing_mode = "cloud"

    cloud_providers = [
        {"name": "openai", "available": data["has_openai_key"]},
        {"name": "anthropic", "available": data["has_anthropic_key"]},
        {"name": "gemini", "available": data["has_google_key"]},
    ]

    # active_model is what Chat.tsx sends as the model parameter to /qa.
    # For private mode: the first available Ollama model (or the config default).
    # For cloud mode: "" so Chat sends model=null and the backend uses
    # get_effective_routing() which reads the DB-stored key correctly.
    cfg = get_settings()
    if data["mode"] == "private":
        active_model = (
            available_local_models[0] if available_local_models else cfg.LITELLM_DEFAULT_MODEL
        )
    else:
        active_model = ""

    return LLMSettingsResponse(
        mode=data["mode"],
        provider=data["provider"],
        model=data["model"],
        has_openai_key=data["has_openai_key"],
        has_anthropic_key=data["has_anthropic_key"],
        has_google_key=data["has_google_key"],
        processing_mode=processing_mode,
        active_model=active_model,
        available_local_models=available_local_models,
        cloud_providers=cloud_providers,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/llm", response_model=LLMSettingsResponse)
async def get_llm_settings_endpoint(
    db: AsyncSession = Depends(get_db),
) -> LLMSettingsResponse:
    """Return current LLM settings from DB. Never returns raw key values."""
    data = await get_llm_settings(db)
    cfg = get_settings()
    return await _build_response(data, cfg.OLLAMA_URL)


@router.patch("/llm", response_model=LLMSettingsResponse)
async def patch_llm_settings(
    req: LLMSettingsPatch,
    db: AsyncSession = Depends(get_db),
) -> LLMSettingsResponse:
    """Update LLM mode, provider, model, or API keys. Null means 'do not change'."""
    await update_llm_settings(
        db,
        mode=req.mode,
        provider=req.provider,
        model=req.model,
        openai_api_key=req.openai_api_key,
        anthropic_api_key=req.anthropic_api_key,
        google_api_key=req.google_api_key,
    )
    data = await get_llm_settings(db)
    cfg = get_settings()
    return await _build_response(data, cfg.OLLAMA_URL)


# ---------------------------------------------------------------------------
# Web search settings (S142)
# ---------------------------------------------------------------------------


class WebSearchSettingsResponse(BaseModel):
    provider: str   # "none" | "brave" | "tavily" | "duckduckgo"
    enabled: bool   # True when provider != "none"


@router.get("/web-search", response_model=WebSearchSettingsResponse)
async def get_web_search_settings() -> WebSearchSettingsResponse:
    """Return current web search provider status for the Chat UI toggle."""
    cfg = get_settings()
    provider = cfg.WEB_SEARCH_PROVIDER
    return WebSearchSettingsResponse(
        provider=provider,
        enabled=(provider != "none"),
    )
