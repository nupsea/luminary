"""Settings router — GET and PATCH /settings/llm (DB-backed, mode + encrypted keys)."""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.services.settings_service import (
    get_labs_enabled,
    get_llm_settings,
    set_labs_enabled,
    update_llm_settings,
)
from app.surface_manifest import labs_surfaces

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

_OLLAMA_TIMEOUT = 3.0


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
    # Whether the Ollama server answered at all. Lets first-run tell "Ollama is
    # down" apart from "Ollama is up but no model is pulled" — both otherwise
    # collapse to processing_mode="unavailable". Defaults True so non-private
    # modes and legacy consumers are unaffected.
    ollama_reachable: bool = True


class LLMSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str | None = None
    provider: str | None = None
    model: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None


async def _fetch_ollama_models(ollama_url: str) -> tuple[bool, list[str]]:
    """Return (server_reachable, available_models). Reachable is True when the
    server answers 200, regardless of whether any model is pulled."""
    try:
        async with httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT) as client:
            resp = await client.get(f"{ollama_url}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                return True, [f"ollama/{m['name']}" for m in data.get("models", [])]
    except Exception:
        pass
    return False, []


async def _build_response(data: dict, ollama_url: str) -> LLMSettingsResponse:
    """Merge new DB fields with backward-compat Ollama-derived fields."""
    ollama_reachable, available_local_models = await _fetch_ollama_models(ollama_url)

    if data["mode"] == "private":
        processing_mode = "local" if available_local_models else "unavailable"
    elif data["mode"] == "hybrid":
        processing_mode = "hybrid"
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
        # cloud and hybrid: backend decides routing via get_effective_routing()
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
        ollama_reachable=ollama_reachable,
    )


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


# Model list — fetches available models from each provider

# Hardcoded cost metadata (USD per 1M tokens, input/output).
# Values are approximate list prices; free-tier notes where applicable.
_MODEL_COSTS: dict[str, dict] = {
    # Gemini — only models confirmed available to new API keys
    "gemini-2.5-pro-exp-03-25": {"input": 0.0, "output": 0.0, "note": "Free (experimental)"},
    "gemini-1.5-flash-8b-001": {"input": 0.0375, "output": 0.15, "note": ""},
    "gemini-1.5-pro-001": {"input": 1.25, "output": 5.00, "note": ""},
    "gemini-1.5-pro-002": {"input": 1.25, "output": 5.00, "note": ""},
    # OpenAI. GPT-5 family list prices are omitted here (not confirmed) so the
    # dropdown shows the name without a fabricated price — formatModelOption
    # renders name-only when cost is absent.
    "gpt-5.4": {"note": "frontier"},
    "gpt-5.1": {"note": "frontier"},
    "gpt-5-mini": {"note": "frontier"},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "note": ""},
    "gpt-4o": {"input": 2.50, "output": 10.00, "note": ""},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40, "note": ""},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60, "note": ""},
    "gpt-4.1": {"input": 2.00, "output": 8.00, "note": ""},
    "o4-mini": {"input": 1.10, "output": 4.40, "note": ""},
    "o3-mini": {"input": 1.10, "output": 4.40, "note": ""},
    # Anthropic
    "claude-haiku-4-5-20251001": {"input": 0.25, "output": 1.25, "note": ""},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00, "note": ""},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "note": ""},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00, "note": ""},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00, "note": ""},
}

_ANTHROPIC_MODELS = [
    {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
    {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku"},
    {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
    {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet"},
    {"id": "claude-opus-4-6", "name": "Claude Opus 4.6"},
]

_OPENAI_MODELS = [
    # Latest / most capable first.
    {"id": "gpt-5.4", "name": "GPT-5.4"},
    {"id": "gpt-5.1", "name": "GPT-5.1"},
    {"id": "gpt-5-mini", "name": "GPT-5 mini"},
    {"id": "gpt-4.1", "name": "GPT-4.1"},
    {"id": "gpt-4.1-mini", "name": "GPT-4.1 mini"},
    {"id": "gpt-4.1-nano", "name": "GPT-4.1 nano"},
    {"id": "gpt-4o", "name": "GPT-4o"},
    {"id": "gpt-4o-mini", "name": "GPT-4o mini"},
    {"id": "o4-mini", "name": "o4-mini"},
    {"id": "o3-mini", "name": "o3-mini"},
]

_MODEL_API_TIMEOUT = 5.0


def _attach_costs(models: list[dict]) -> list[dict]:
    """Attach cost metadata to each model dict."""
    result = []
    for m in models:
        mid = m["id"]
        cost = _MODEL_COSTS.get(mid, {})
        result.append(
            {
                **m,
                "cost_input": cost.get("input"),
                "cost_output": cost.get("output"),
                "cost_note": cost.get("note", ""),
            }
        )
    return result


# Model IDs that Google's ListModels API still returns with generateContent support,
# but are no longer usable by new API keys. Confirmed 404/NOT_FOUND in production.
# Includes both short aliases and their versioned (-001/-002) variants.
_DEPRECATED_GEMINI_IDS = {
    "gemini-2.0-flash",  # "no longer available to new users"
    "gemini-2.0-flash-001",  # versioned variant — same restriction
    "gemini-2.0-flash-lite",  # "no longer available to new users"
    "gemini-2.0-flash-lite-001",  # versioned variant — confirmed 404
    "gemini-1.5-flash",  # "not found for API version v1beta"
    "gemini-1.5-flash-001",  # versioned variant — same restriction
    "gemini-1.5-flash-002",  # versioned variant — same restriction
}


async def _list_gemini_models(api_key: str) -> list[dict]:
    """Call Google's ListModels API and return models that support generateContent.

    Filters out model IDs in _DEPRECATED_GEMINI_IDS which the API still lists but
    returns 404 for new API keys.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}&pageSize=50"
    try:
        async with httpx.AsyncClient(timeout=_MODEL_API_TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(
                    "Gemini ListModels returned %d: %s", resp.status_code, resp.text[:200]
                )
                return []
            data = resp.json()
    except Exception as exc:
        logger.warning("Gemini ListModels failed: %s", exc)
        return []

    models = []
    for m in data.get("models", []):
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        raw_name = m.get("name", "")  # e.g. "models/gemini-1.5-flash-001"
        model_id = raw_name.replace("models/", "")
        if model_id in _DEPRECATED_GEMINI_IDS:
            continue
        display = m.get("displayName") or model_id
        models.append({"id": model_id, "name": display})

    # Sort: known models first (by _MODEL_COSTS key order), then alphabetical
    known_order = list(_MODEL_COSTS.keys())
    models.sort(
        key=lambda m: (known_order.index(m["id"]) if m["id"] in known_order else 999, m["id"])
    )
    return models


@router.get("/llm/models")
async def list_llm_models(
    provider: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return available models for the given provider with cost info.

    For Gemini: fetches live from Google's ListModels API using the stored key.
    For OpenAI/Anthropic: returns a curated list (no live fetch needed).
    """
    if provider == "gemini":
        from app.services.settings_service import _cache  # noqa: PLC0415

        api_key = _cache.get("google_api_key", "")
        if not api_key:
            return []
        models = await _list_gemini_models(api_key)
        return _attach_costs(models)

    if provider == "openai":
        return _attach_costs(_OPENAI_MODELS)

    if provider == "anthropic":
        return _attach_costs(_ANTHROPIC_MODELS)

    return []


# Web search settings


class WebSearchSettingsResponse(BaseModel):
    provider: str  # "none" | "brave" | "tavily" | "duckduckgo"
    enabled: bool  # True when provider != "none"


@router.get("/web-search", response_model=WebSearchSettingsResponse)
async def get_web_search_settings() -> WebSearchSettingsResponse:
    """Return current web search provider status for the Chat UI toggle."""
    cfg = get_settings()
    provider = cfg.WEB_SEARCH_PROVIDER
    return WebSearchSettingsResponse(
        provider=provider,
        enabled=(provider != "none"),
    )


# Surface tier + labs toggles


class LabsSurface(BaseModel):
    id: str
    label: str
    description: str | None = None
    default_off: bool = False


class SurfaceResponse(BaseModel):
    tier: str
    labs_enabled: list[str]
    available_labs: list[LabsSurface]


class LabsPatch(BaseModel):
    labs_enabled: list[str]


def _available_labs() -> list[LabsSurface]:
    return [
        LabsSurface(
            id=s["id"],
            label=s["labels"]["en"],
            description=s.get("description"),
            default_off=bool(s.get("default_off", False)),
        )
        for s in labs_surfaces()
    ]


@router.get("/surface", response_model=SurfaceResponse)
async def get_surface(db: AsyncSession = Depends(get_db)) -> SurfaceResponse:
    return SurfaceResponse(
        tier=get_settings().LUMINARY_SURFACE_TIER,
        labs_enabled=sorted(await get_labs_enabled(db)),
        available_labs=_available_labs(),
    )


@router.patch("/labs", response_model=SurfaceResponse)
async def patch_labs(
    body: LabsPatch, db: AsyncSession = Depends(get_db)
) -> SurfaceResponse:
    if get_settings().LUMINARY_SURFACE_TIER == "public":
        raise HTTPException(status_code=400, detail="labs are not available on a public build")
    try:
        await set_labs_enabled(db, set(body.labs_enabled))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SurfaceResponse(
        tier=get_settings().LUMINARY_SURFACE_TIER,
        labs_enabled=sorted(await get_labs_enabled(db)),
        available_labs=_available_labs(),
    )
