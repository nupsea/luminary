"""Which cloud models a provider offers, what each costs, and whether a key works.

The curated lists are the fallback before a key is saved and the order of what a
live listing returns; with a key, the provider's own endpoint decides. Prices come
from litellm's bundled cost map (I-18: never fetched), so none is typed here.
"""

import asyncio
import logging
from typing import Literal

import httpx
import litellm

from app.services import network_errors

logger = logging.getLogger(__name__)

Provider = Literal["openai", "anthropic", "gemini"]

PROVIDER_LABELS: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
}

# Recommended first; each provider's own models page is the source.
_CURATED: dict[str, list[dict[str, str]]] = {
    "openai": [
        {"id": "gpt-6-luna", "name": "GPT-6 Luna"},
        {"id": "gpt-6.1-sol", "name": "GPT-6.1 Sol"},
        {"id": "gpt-6-astra", "name": "GPT-6 Astra"},
        {"id": "gpt-5.6-sol", "name": "GPT-5.6 Sol"},
    ],
    "anthropic": [
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
        {"id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5"},
        {"id": "claude-opus-5-5", "name": "Claude Opus 5.5"},
        {"id": "claude-fable-5-1", "name": "Claude Fable 5.1"},
    ],
    "gemini": [
        {"id": "gemini-3.8-flash", "name": "Gemini 3.8 Flash"},
        {"id": "gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash-Lite"},
        {"id": "gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro (preview)"},
        {"id": "gemini-3.6-flash", "name": "Gemini 3.6 Flash"},
        {"id": "gemini-3.1-flash-lite", "name": "Gemini 3.1 Flash-Lite"},
    ],
}

# Each provider's fast tier: what a provider choice carries when no model is
# named (I-53), and what Settings marks as recommended.
PROVIDER_DEFAULT_MODEL: dict[str, str] = {p: models[0]["id"] for p, models in _CURATED.items()}

# Google's ListModels still returns these with generateContent; new keys get 404.
_RETIRED_GEMINI_IDS = {
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-lite-001",
    "gemini-1.5-flash",
    "gemini-1.5-flash-001",
    "gemini-1.5-flash-002",
}

# Families a provider's model listing returns that are never chat, whatever the
# version. An id absent from litellm's cost map is otherwise kept: it is more
# likely newer than the snapshot than an obscure non-chat model.
_NON_CHAT_PREFIXES = (
    "babbage",
    "dall-e",
    "davinci",
    "gpt-image",
    "omni-moderation",
    "sora",
    "text-embedding",
    "text-moderation",
    "tts-",
    "whisper",
)

_LIST_TIMEOUT = 5.0
_KEY_CHECK_TIMEOUT = 8.0


def _is_chat_model(model_id: str) -> bool:
    bare = model_id.split("/", 1)[-1]
    if bare.startswith(_NON_CHAT_PREFIXES):
        return False
    mode = litellm.model_cost.get(model_id, {}).get("mode")
    if mode is None:
        mode = litellm.model_cost.get(bare, {}).get("mode")
    return mode is None or mode == "chat"


def reads_images(model: str) -> bool:
    """Whether the routed `provider/id` *model* accepts an image.

    Every curated model does. Any other id needs litellm's map to say so; unknown
    stays False so a text-only model never receives a figure.
    """
    provider, _, model_id = model.partition("/")
    if any(m["id"] == model_id for m in _CURATED.get(provider, [])):
        return True
    entry = litellm.model_cost.get(model) or litellm.model_cost.get(model_id) or {}
    return bool(entry.get("supports_vision"))


def _strip_provider_prefix(model_id: str, provider: str) -> str:
    """litellm's OpenAI listing returns bare ids, its Anthropic one `anthropic/<id>`.

    Every consumer re-attaches the prefix, so a prefixed id would route to
    `anthropic/anthropic/claude-...`.
    """
    return model_id[len(provider) + 1 :] if model_id.startswith(f"{provider}/") else model_id


def _price_per_million(provider: str, model_id: str) -> tuple[float | None, float | None]:
    """List price from litellm's cost map, or (None, None) when it has none."""
    entry = litellm.model_cost.get(f"{provider}/{model_id}") or litellm.model_cost.get(model_id)
    if not entry:
        return None, None
    inp, out = entry.get("input_cost_per_token"), entry.get("output_cost_per_token")
    if inp is None or out is None:
        return None, None
    return round(inp * 1_000_000, 4), round(out * 1_000_000, 4)


def _present(provider: str, models: list[dict[str, str]]) -> list[dict]:
    """Curated order first, then the rest by id, each with its price and flags."""
    curated = _CURATED.get(provider, [])
    order = [m["id"] for m in curated]
    names = {m["id"]: m["name"] for m in curated}
    models = sorted(
        models,
        key=lambda m: (order.index(m["id"]) if m["id"] in order else len(order), m["id"]),
    )
    out = []
    for m in models:
        cost_in, cost_out = _price_per_million(provider, m["id"])
        out.append(
            {
                "id": m["id"],
                "name": names.get(m["id"]) or m.get("name") or m["id"],
                "cost_input": cost_in,
                "cost_output": cost_out,
                "cost_note": "preview" if "preview" in m["id"] or "-exp" in m["id"] else "",
                "recommended": m["id"] == PROVIDER_DEFAULT_MODEL.get(provider),
            }
        )
    return out


async def _list_gemini_live(api_key: str) -> list[dict[str, str]]:
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    try:
        async with httpx.AsyncClient(timeout=_LIST_TIMEOUT) as client:
            resp = await client.get(
                url, params={"pageSize": 1000}, headers={"x-goog-api-key": api_key}
            )
        if resp.status_code != 200:
            logger.warning("Gemini ListModels returned %d", resp.status_code)
            return []
        data = resp.json()
    except Exception as exc:
        logger.warning("Gemini ListModels failed: %s", exc)
        return []

    models = []
    for m in data.get("models", []):
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        model_id = m.get("name", "").removeprefix("models/")
        if not model_id or model_id in _RETIRED_GEMINI_IDS:
            continue
        if not _is_chat_model(f"gemini/{model_id}"):
            continue
        models.append({"id": model_id, "name": m.get("displayName") or model_id})
    return models


async def _list_litellm_live(provider: str, api_key: str) -> list[dict[str, str]]:
    try:
        # litellm's provider `get_models` is a synchronous HTTP call.
        raw_ids = await asyncio.to_thread(
            litellm.get_valid_models,
            check_provider_endpoint=True,
            custom_llm_provider=provider,
            api_key=api_key,
        )
    except Exception as exc:
        logger.warning("%s model list failed: %s", provider, exc)
        return []
    seen: set[str] = set()
    models = []
    for raw in raw_ids:
        mid = _strip_provider_prefix(raw, provider)
        if mid and mid not in seen and _is_chat_model(mid):
            seen.add(mid)
            models.append({"id": mid, "name": mid})
    return models


async def list_models(provider: str, api_key: str) -> list[dict]:
    """What *api_key* can reach; the curated list when there is no key or no answer."""
    if provider not in _CURATED:
        return []
    live: list[dict[str, str]] = []
    if api_key:
        if provider == "gemini":
            live = await _list_gemini_live(api_key)
        else:
            live = await _list_litellm_live(provider, api_key)
    return _present(provider, live or _CURATED[provider])


KeyStatus = Literal["verified", "rejected", "unchecked"]

_KEY_CHECKS: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1/models", "Authorization"),
    "anthropic": ("https://api.anthropic.com/v1/models", "x-api-key"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/models", "x-goog-api-key"),
}


async def check_key(provider: str, api_key: str) -> tuple[KeyStatus, str]:
    """Ask the provider whether it accepts *api_key*, with a sentence for the user.

    Listing models costs nothing and needs the same authentication as a
    completion. `unchecked` means the provider could not answer, which says
    nothing about the key.
    """
    url, header = _KEY_CHECKS[provider]
    label = PROVIDER_LABELS[provider]
    headers = {header: f"Bearer {api_key}" if header == "Authorization" else api_key}
    if provider == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
    try:
        async with httpx.AsyncClient(timeout=_KEY_CHECK_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
    except Exception as exc:
        why = network_errors.explain(str(exc)) or "The request failed."
        return "unchecked", f"Saved, but {label} could not be reached to check it. {why}"
    if resp.status_code == 200:
        return "verified", f"{label} accepted this key."
    # Google answers a bad key with 400 API_KEY_INVALID, but also uses 400 for an
    # unsupported region, which no other key would fix.
    bad_key_400 = resp.status_code == 400 and "API_KEY" in resp.text
    if resp.status_code in (401, 403) or bad_key_400:
        return (
            "rejected",
            f"{label} rejected this key ({resp.status_code}). "
            "Check it was copied whole, then paste it again.",
        )
    return (
        "unchecked",
        f"Saved, but {label} answered {resp.status_code}, so the key could not be checked."
        + (f" {label} said: {said}" if (said := _provider_message(resp)) else ""),
    )


def _provider_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message", "") if isinstance(error, dict) else ""
    return message[:200]
