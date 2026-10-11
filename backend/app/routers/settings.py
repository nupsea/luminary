"""Settings router — GET and PATCH /settings/llm (DB-backed, mode + encrypted keys)."""

import logging
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.services.background import fire_and_forget, task_registry
from app.services.background_prefs import (
    chapter_backfill,
    quiet_background,
    set_background_prefs,
)
from app.services.cloud_models import PROVIDER_LABELS, list_models
from app.services.settings_service import (
    get_llm_settings,
    get_rerank_enabled,
    previewing_routing,
    resolve_provider_api_key,
    save_provider_key,
    set_rerank_enabled,
    update_llm_settings,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

_background_tasks = task_registry(__name__)

_OLLAMA_TIMEOUT = 3.0


class LLMSettingsResponse(BaseModel):
    # DB-backed new fields
    mode: str
    provider: str
    model: str
    # The on-device models, resolved: the stored choice or the configured default.
    local_chat_model: str = ""
    vision_model: str = ""
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
    # Whether anyone ever answered the engine question, which is not the same as
    # what the mode is: a library that predates the question runs `private`
    # because that is the default. False is what lets an existing library be
    # offered the choice its first run never asked (roadmap 0.10.0).
    mode_chosen: bool = False
    # The learner waved that offer away without answering. Kept apart from
    # `mode_chosen` so declining to decide is not recorded as a decision.
    offer_dismissed: bool = False
    # Whether a key saved here reaches an OS keychain. False in a container,
    # where it is written to the library instead -- which the dialog must say
    # rather than promise the keychain everywhere.
    keyring_available: bool = True


class LLMSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # An unknown mode was stored as-is, and routing treats anything but private
    # and hybrid as cloud.
    mode: Literal["private", "hybrid", "cloud"] | None = None
    provider: str | None = None
    model: str | None = None
    # "" clears the override and falls back to the configured default.
    local_chat_model: str | None = None
    vision_model: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    offer_dismissed: bool | None = None


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
        logger.debug("Ollama probe failed at %s", ollama_url, exc_info=True)
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
    # For cloud mode: "" so Chat sends model=null and the backend uses
    # get_effective_routing() which reads the DB-stored key correctly.
    if data["mode"] == "private":
        # The model actually routed to, not the first one Ollama happens to
        # list -- those disagreed, so the UI reported a model the backend was
        # not using.
        active_model = data["local_chat_model"]
    else:
        # cloud and hybrid: backend decides routing via get_effective_routing()
        active_model = ""

    return LLMSettingsResponse(
        mode=data["mode"],
        provider=data["provider"],
        model=data["model"],
        local_chat_model=data["local_chat_model"],
        vision_model=data["vision_model"],
        has_openai_key=data["has_openai_key"],
        has_anthropic_key=data["has_anthropic_key"],
        has_google_key=data["has_google_key"],
        processing_mode=processing_mode,
        active_model=active_model,
        available_local_models=available_local_models,
        cloud_providers=cloud_providers,
        ollama_reachable=ollama_reachable,
        mode_chosen=data["mode_chosen"],
        offer_dismissed=data["offer_dismissed"],
        keyring_available=data["keyring_available"],
    )


class RoleResolution(BaseModel):
    model: str
    local: bool
    # None when the model is not in the registry: unmeasured, which is not the
    # same as weightless and must not be rendered as 0.
    resident_gb: float | None = None
    fallback_reason: str | None = None


class ModelResidencyResponse(BaseModel):
    """What this configuration costs on this machine, and whether it fits.

    Every number here was knowable before and none was put together, so a model
    too large for the host was selectable and the first symptom was a crash
    during ingestion rather than a refusal at the point of choosing.
    """

    profile: str
    profile_explicit: bool
    profile_suits_host: bool
    host_ram_gb: int
    roles: dict[str, RoleResolution]
    resident_models: list[str]
    resident_count: int
    max_resident: int
    within_residency_limit: bool
    resident_gb: float
    unmeasured_models: list[str]
    oversized_models: list[str]
    # Roles where the host overruled the configured model, keyed by role, each
    # carrying `configured`, `resolved` and `reason`. Empty when every configured
    # model was honoured. A narrowed model is absent from `oversized_models`
    # because it is not in play at all, so without this the report described a
    # model the user never chose and flagged nothing.
    narrowed_defaults: dict[str, dict[str, str]] = {}
    # The half-of-RAM budget the registry sizes every model against, applied to
    # the set that actually resolves. `within_residency_limit` counts runners,
    # which is a different question from whether the machine can hold them.
    resident_budget_gb: float | None = None
    resident_set_fits: bool = True
    # Text-producing roles answering with a local model that is not in the
    # measured text order, keyed by role, each carrying `model` and `multimodal`.
    # This report only ever checked size, so a shipped install ran a figure
    # reader as its chat model with every field clean and worse answers as the
    # only symptom.
    unranked_text_roles: dict[str, dict[str, object]] = {}


class InstallableModel(BaseModel):
    id: str
    resident_gb: float
    min_ram_gb: int
    licence: str
    multimodal: bool
    usable_context: int
    # False means the model matrix has never run against this entry, so
    # `accommodations_needed` being empty means nobody looked.
    accommodations_measured: bool
    fits_host: bool


class WorkRoutingItem(BaseModel):
    id: str
    label: str
    model: str | None
    on_device: bool
    routable: bool
    why: str
    fallback_reason: str | None = None
    refused_reason: str | None = None


class RoutingResponse(BaseModel):
    """Where each unit of work runs under the current mode.

    `leaves_device` is derived from the rows rather than stated beside them, so a
    row and the summary cannot disagree.
    """

    mode: str
    provider: str | None
    work: list[WorkRoutingItem]
    leaves_device: list[str]
    # Null when nothing measured local inference on this host. Kept nullable rather
    # than defaulted so a screen quoting it cannot quote a number nobody took.
    local_probe_seconds: float | None = None


@router.get("/llm/routing", response_model=RoutingResponse)
async def get_llm_routing(
    mode: Literal["private", "hybrid", "cloud"] | None = None,
    provider: Literal["openai", "anthropic", "gemini"] | None = None,
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None,
) -> RoutingResponse:
    """Which engine serves each unit of work, and what that means leaves the machine.

    With any of *mode*, *provider* or *model*, the report is for that unsaved choice,
    resolved by the same code; nothing is saved.
    """
    from app.services.llm_routing import routing_report  # noqa: PLC0415

    with previewing_routing(mode, provider, model):
        report = routing_report()
    return RoutingResponse(
        mode=report.mode,
        provider=report.provider,
        work=[WorkRoutingItem(**vars(w)) for w in report.work],
        leaves_device=report.leaves_device,
        local_probe_seconds=report.local_probe_seconds,
    )


@router.get("/models", response_model=ModelResidencyResponse)
async def get_model_residency() -> ModelResidencyResponse:
    """The active memory profile, what each role resolves to, and the footprint."""
    from app.services.model_router import residency_report  # noqa: PLC0415

    return ModelResidencyResponse(**residency_report())


@router.get("/models/catalogue", response_model=list[InstallableModel])
async def get_model_catalogue() -> list[InstallableModel]:
    """Every registry entry with its footprint, smallest first.

    Includes models this host cannot hold, flagged rather than hidden: a user
    choosing a machine or deciding what to pull is better served by seeing what
    exists and what it would need.
    """
    from app.model_registry import REGISTRY, fits_host  # noqa: PLC0415

    entries = sorted(REGISTRY.values(), key=lambda p: p.resident_bytes)
    return [
        InstallableModel(
            id=p.id,
            resident_gb=p.resident_gb,
            min_ram_gb=p.min_ram_gb,
            licence=p.licence,
            multimodal=p.multimodal,
            usable_context=p.usable_context,
            accommodations_measured=p.accommodations_measured,
            fits_host=fits_host(p),
        )
        for p in entries
    ]


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
    from app.services.llm_routing import refusal  # noqa: PLC0415

    background_was_refused = refusal("background") is not None
    await update_llm_settings(
        db,
        mode=req.mode,
        provider=req.provider,
        model=req.model,
        local_chat_model=req.local_chat_model,
        vision_model=req.vision_model,
        offer_dismissed=req.offer_dismissed,
        openai_api_key=req.openai_api_key,
        anthropic_api_key=req.anthropic_api_key,
        google_api_key=req.google_api_key,
    )
    if background_was_refused and refusal("background") is None:
        await _resume_background_work()
    data = await get_llm_settings(db)
    cfg = get_settings()
    return await _build_response(data, cfg.OLLAMA_URL)


async def _resume_background_work() -> None:
    """Run the work the previous settings refused on this host.

    Only on that transition: a mode change on a host that could already run it has
    nothing owed, and must not start a library-wide summary pass as a side effect.
    """
    from app.services.enrichment_worker import requeue_skipped_jobs  # noqa: PLC0415
    from app.services.section_summarizer import (  # noqa: PLC0415
        resummarize_documents_missing_summaries,
    )

    await requeue_skipped_jobs()
    fire_and_forget(
        resummarize_documents_missing_summaries(),
        _background_tasks,
        label="summary repair after mode change",
    )


# Cloud models and keys


class CloudModel(BaseModel):
    id: str
    name: str
    # USD per 1M tokens from litellm's cost map; None when it has no price.
    cost_input: float | None = None
    cost_output: float | None = None
    cost_note: str = ""
    recommended: bool = False


@router.get("/llm/models", response_model=list[CloudModel])
async def list_llm_models(provider: str) -> list[CloudModel]:
    """Models the stored key for *provider* can reach; a curated list without one."""
    api_key = resolve_provider_api_key(provider) if provider in PROVIDER_LABELS else ""
    return [CloudModel(**m) for m in await list_models(provider, api_key)]


class ProviderKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai", "anthropic", "gemini"]
    api_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ProviderKeyResponse(BaseModel):
    # verified: the provider accepted it. rejected: refused, and not saved.
    # unchecked: saved, but the provider could not be asked.
    status: Literal["verified", "rejected", "unchecked"]
    saved: bool
    message: str


@router.post("/llm/key", response_model=ProviderKeyResponse)
async def save_llm_key(
    req: ProviderKeyRequest,
    db: AsyncSession = Depends(get_db),
) -> ProviderKeyResponse:
    """Check a provider key with the provider, then keep it unless it was refused."""
    status, message = await save_provider_key(db, req.provider, req.api_key)
    return ProviderKeyResponse(status=status, saved=status != "rejected", message=message)


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


# Retrieval settings


class RetrievalSettingsResponse(BaseModel):
    rerank_enabled: bool


class RetrievalSettingsPatch(BaseModel):
    rerank_enabled: bool


@router.get("/retrieval", response_model=RetrievalSettingsResponse)
async def get_retrieval_settings(
    db: AsyncSession = Depends(get_db),
) -> RetrievalSettingsResponse:
    return RetrievalSettingsResponse(rerank_enabled=await get_rerank_enabled(db))


@router.patch("/retrieval", response_model=RetrievalSettingsResponse)
async def patch_retrieval_settings(
    body: RetrievalSettingsPatch, db: AsyncSession = Depends(get_db)
) -> RetrievalSettingsResponse:
    await set_rerank_enabled(db, body.rerank_enabled)
    return RetrievalSettingsResponse(rerank_enabled=await get_rerank_enabled(db))


# Background work


class BackgroundSettingsResponse(BaseModel):
    chapter_backfill: bool
    quiet_background: bool


class BackgroundSettingsPatch(BaseModel):
    chapter_backfill: bool | None = None
    quiet_background: bool | None = None


def _background_settings() -> BackgroundSettingsResponse:
    return BackgroundSettingsResponse(
        chapter_backfill=chapter_backfill(), quiet_background=quiet_background()
    )


@router.get("/background", response_model=BackgroundSettingsResponse)
async def get_background_settings() -> BackgroundSettingsResponse:
    return _background_settings()


@router.patch("/background", response_model=BackgroundSettingsResponse)
async def patch_background_settings(
    body: BackgroundSettingsPatch, db: AsyncSession = Depends(get_db)
) -> BackgroundSettingsResponse:
    await set_background_prefs(
        db, chapter_backfill=body.chapter_backfill, quiet_background=body.quiet_background
    )
    return _background_settings()
