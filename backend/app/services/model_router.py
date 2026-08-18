"""One entry point for "which model serves this work".

Call sites name the work -- chat, generation, background, vision -- and this
resolves it. They used to name the model, in five places, two of which read
`config` directly and so never saw the model a user chose in Settings: a
Settings change silently did not apply to flashcard generation.

Resolution order per role:

  chat / background   `settings_service.get_effective_routing`, which is what
                      LLMService itself calls. Both arms exist because `hybrid`
                      sends interactive work to the cloud and background work to
                      Ollama; a single answer would describe a system that does
                      not exist.
  generation          the explicit `LITELLM_GENERATION_MODEL` override when set,
                      otherwise whatever chat resolves to. The override is a
                      deliberate escape hatch for "generate with something
                      stronger"; without it, Settings governs.
  vision              `settings_service.get_vision_model`.

`resolve` never raises. A cloud route missing its key resolves to the local
model with a reason attached, because refusing to answer here would take down
ingestion for a configuration problem the user can see in Settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.model_registry import (
    _GB,
    ROLES,
    ModelProfile,
    Role,
    configured_generation_override,
    fits_host,
    profile_for,
)
from app.services import settings_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelChoice:
    role: Role
    model: str
    api_key: str | None
    profile: ModelProfile | None
    # True only when an override names this model explicitly. A caller that
    # pins a model tells LLMService to skip its own routing, which also skips
    # the API key that routing supplies and the offline reroute -- so "no
    # override configured" must stay distinguishable from "this exact model".
    explicit: bool = False
    # Set when the resolution fell back. Reported, never swallowed: a run served
    # by a fallback measured a different system than the one asked for.
    fallback_reason: str | None = None

    @property
    def is_local(self) -> bool:
        return self.model.startswith("ollama/")


def resolve(role: Role, *, background: bool = False) -> ModelChoice:
    """The model this backend would actually call for *role*."""
    if role == "vision":
        override = settings_service.configured_vision_override()
        if override:
            return ModelChoice(role, override, None, profile_for(override), explicit=True)
        # Sharing is a remedy for a host that cannot hold two models, not a
        # preference. On a machine with room for a dedicated reader, the
        # configured one is kept -- quietly retargeting vision on a 32GB laptop
        # because a chat model happens to also have eyes would be this code
        # overruling a deployment decision nobody asked it to revisit.
        #
        # "Room" is the residency limit, not host RAM. Gating on RAM alone left a
        # 36GB machine running the low profile resolving two models against a
        # limit of one: the reader fitted the host and the profile still forbade
        # it. That is the case the bundled app hits when it sizes itself down, and
        # the case anyone hits by choosing the profile deliberately.
        from app.memory_profile import max_resident_models  # noqa: PLC0415

        configured = settings_service.get_vision_model()
        profile = profile_for(configured)
        fits = profile is None or fits_host(profile)
        room_for_two = max_resident_models() > 1
        if fits and room_for_two:
            return ModelChoice(role, configured, None, profile)
        model = _shared_vision_model() or configured
        return ModelChoice(role, model, None, profile_for(model))

    if role == "generation":
        override = configured_generation_override()
        if override:
            return ModelChoice(role, override, None, profile_for(override), explicit=True)
        role_background = background

    else:
        role_background = background or role == "background"

    try:
        model, api_key = settings_service.get_effective_routing(background=role_background)
        return ModelChoice(role, model, api_key, profile_for(model))
    except ValueError as exc:
        local = settings_service.get_local_chat_model()
        return ModelChoice(role, local, None, profile_for(local), fallback_reason=str(exc))


def _shared_vision_model() -> str | None:
    """The model already answering another role, when it can also read a figure.

    On an 8GB host `max_resident_models` is 1, so a separate vision model is not
    a second model -- it is the reason nothing fits. Before this, the vision role
    resolved to a 6.81GB entry needing 16GB and the low profile had *zero*
    feasible assignments across all four roles. Reusing the model that is already
    resident makes the whole profile satisfiable with one model.

    Only ever returns a model that is both multimodal and fits the host, so this
    can widen what is possible and never narrow it. Consulted only when the
    configured reader does not fit -- see the vision branch of `resolve`.
    """
    for role in ("chat", "generation"):
        try:
            model = resolve(role).model
        except Exception:  # noqa: BLE001
            logger.debug("vision reuse: role %s does not resolve", role, exc_info=True)
            continue
        profile = profile_for(model)
        if profile is not None and profile.multimodal and fits_host(profile):
            return model
    return None


def resident_models() -> set[str]:
    """Distinct models the current configuration would keep loaded.

    A memory profile constrains this set: two roles resolving to different ids
    cost two runners whatever `OLLAMA_MAX_LOADED_MODELS` says (I-31). The
    residency test in plan Phase 7 asserts against exactly this.
    """
    return {resolve(role).model for role in ROLES}


def residency_report() -> dict[str, Any]:
    """What this configuration costs on this machine, and whether it fits.

    The three numbers that decide whether a machine can run this configuration
    were each knowable and none was ever put together: how much RAM the host
    has, how many distinct models the four roles resolve to, and what those
    models weigh. A configuration that exceeds the host is reported here rather
    than discovered as a crash during ingestion.

    Cloud models weigh nothing locally and are excluded from the footprint;
    unregistered local models are listed as unmeasured, because an unknown
    footprint must not be silently counted as zero.
    """
    from app.memory_profile import (  # noqa: PLC0415
        active_profile,
        host_ram_gb,
        max_resident_models,
        profile_is_explicit,
        profile_suits_host,
    )

    per_role = {role: resolve(role) for role in ROLES}
    local = {c.model for c in per_role.values() if c.is_local}

    measured_bytes = 0
    unmeasured: list[str] = []
    for model in sorted(local):
        profile = profile_for(model)
        if profile is None:
            unmeasured.append(model)
        else:
            measured_bytes += profile.resident_bytes

    profile_name = active_profile()
    limit = max_resident_models(profile_name)
    ram = host_ram_gb()

    oversized = sorted(
        {
            model
            for model in local
            if (p := profile_for(model)) is not None and not fits_host(p, ram or None)
        }
    )

    return {
        "profile": profile_name,
        "profile_explicit": profile_is_explicit(),
        "profile_suits_host": profile_suits_host(profile_name),
        "host_ram_gb": ram,
        "roles": {
            role: {
                "model": choice.model,
                "local": choice.is_local,
                "resident_gb": (p.resident_gb if (p := profile_for(choice.model)) else None),
                "fallback_reason": choice.fallback_reason,
            }
            for role, choice in per_role.items()
        },
        "resident_models": sorted(local),
        "resident_count": len(local),
        "max_resident": limit,
        "within_residency_limit": len(local) <= limit,
        "resident_gb": round(measured_bytes / _GB, 2),
        "unmeasured_models": unmeasured,
        "oversized_models": oversized,
    }
