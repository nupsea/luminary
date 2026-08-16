"""What each model costs and what it can do, in one place.

Model choice resolved in five places before this, two of which bypassed the
settings service entirely -- so a model chosen in Settings never reached
flashcard generation. Worse for the plan this serves: nothing recorded what a
model *needs*, so adopting one was an act of hope rather than an audit.

A profile carries both halves:

  footprint    resident bytes, licence, the RAM below which it should not be
               offered. What a memory profile constrains.
  capability   context, JSON support, whether it thinks by default, and the
               accommodations it still needs. What a prompt renders against.

Config layer: this module reads `config`, and nothing in `services/` or
`routers/` reads a model name out of config again. `tests/test_model_registry.py`
fails if that returns.

`accommodations_needed` is empty for every entry until the model matrix
measures it (plan Phase 6). Empty means unmeasured, not "needs nothing" -- the
distinction matters, because a model with no measured accommodations is a model
nobody has run the matrix against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.config import get_settings

Role = Literal["chat", "generation", "background", "vision"]

# The four kinds of work a model is asked to do. Call sites name the work; what
# answers is a resolution, never a hardcoded id.
ROLES: tuple[Role, ...] = ("chat", "generation", "background", "vision")

_GB = 1024**3


@dataclass(frozen=True)
class ModelProfile:
    id: str
    licence: str
    # Resident bytes with a typical quantisation and one KV cache. Estimates
    # until `scripts/mem_profile.py` measures the model in place.
    resident_bytes: int
    # Below this, the model should not be offered on a machine at all.
    min_ram_gb: int
    usable_context: int
    supports_json_schema: bool
    # Thinking traces burn num_ctx before an answer token and return an empty
    # /qa; every local call sets think=False for this reason (I-27).
    thinking_default: bool
    multimodal: bool = False
    # Set by the model matrix when it has run against this model. Until then,
    # `accommodations_needed` being empty means nobody looked -- not that the
    # model needs nothing.
    accommodations_measured: bool = False
    # Filled by the model matrix, never authored.
    accommodations_needed: tuple[str, ...] = field(default_factory=tuple)

    @property
    def resident_gb(self) -> float:
        return round(self.resident_bytes / _GB, 2)


# Every footprint below is MEASURED, by `scripts/model_footprint.py`, from
# Ollama's own `/api/ps` after a real generation at the deployed `OLLAMA_NUM_CTX`
# of 8192 -- weights plus one KV cache, which is what `resident_bytes` means.
# Re-measure rather than adjust: the estimates these replaced were low by up to
# 44% (llama3.2 was carried at 2.0GB and weighs 2.88GB), and these numbers now
# decide whether a model is offered on someone's laptop.
#
# `min_ram_gb` is the one derived value and it is policy, not measurement: twice
# the resident size rounded up to a RAM tier, the model taking half the machine
# while the other half carries the OS, the backend (4.7GB peak during ingest),
# the embedder and the entity model. The rule reproduces every value that was
# hand-written here before it existed.
#
# `usable_context` is a deployment decision and deliberately NOT the advertised
# window: llama3.2 and phi4-mini advertise 131072 and qwen3.5 262144, but a slot
# costs a full window of KV cache (I-31) and one value is in force per loaded
# model (I-27). The advertised figure is a capability, never a budget.
MEASURED_AT_NUM_CTX = 8192

REGISTRY: dict[str, ModelProfile] = {
    "ollama/llama3.2": ModelProfile(
        id="ollama/llama3.2",
        licence="Llama 3.2 Community License",
        resident_bytes=3092376453,  # 2.88GB
        min_ram_gb=8,
        usable_context=8192,
        supports_json_schema=True,
        thinking_default=False,
    ),
    "ollama/qwen3.5:4b": ModelProfile(
        id="ollama/qwen3.5:4b",
        licence="Apache-2.0",
        resident_bytes=3446960783,  # 3.21GB
        min_ram_gb=8,
        usable_context=8192,
        supports_json_schema=True,
        # The only candidate in this class that reasons unless told not to. Every
        # local call sets think=False (I-27); without it this model put an entire
        # JSON object into the `thinking` field and returned an empty `response`,
        # which is the empty-/qa failure that rule exists to prevent.
        thinking_default=True,
    ),
    "ollama/phi4-mini": ModelProfile(
        id="ollama/phi4-mini",
        licence="MIT",
        resident_bytes=3704409292,  # 3.45GB
        min_ram_gb=8,
        usable_context=8192,
        supports_json_schema=True,
        thinking_default=False,
    ),
    "ollama/gemma3:4b": ModelProfile(
        id="ollama/gemma3:4b",
        licence="Gemma Terms of Use",
        resident_bytes=3887002419,  # 3.62GB
        min_ram_gb=8,
        usable_context=8192,
        supports_json_schema=True,
        thinking_default=False,
    ),
    "ollama/qwen2.5vl:7b": ModelProfile(
        id="ollama/qwen2.5vl:7b",
        licence="Apache-2.0",
        resident_bytes=7311392768,  # 6.81GB
        min_ram_gb=16,
        usable_context=8192,
        supports_json_schema=True,
        thinking_default=False,
        multimodal=True,
    ),
    "ollama/qwen2.5:14b-instruct": ModelProfile(
        id="ollama/qwen2.5:14b-instruct",
        licence="Apache-2.0",
        resident_bytes=10383085076,  # 9.67GB
        min_ram_gb=24,
        usable_context=8192,
        supports_json_schema=True,
        thinking_default=False,
    ),
}


def profile_for(model_id: str) -> ModelProfile | None:
    """The profile for a model id, or None when it is not in the registry.

    None is a real answer: a user may point Settings at any model Ollama holds,
    or at a cloud model. Callers degrade rather than refuse -- but a run against
    an unregistered model has no measured footprint or capability, and anything
    reporting the run should say so.
    """
    return REGISTRY.get(model_id) or REGISTRY.get(f"ollama/{model_id}")


def fits_host(profile: ModelProfile, ram_gb: int | None = None) -> bool:
    """Whether this machine has the RAM the model asks for.

    `min_ram_gb` sat unread on every entry until this existed, so a 10GB model
    was selectable on a 16GB laptop and the first symptom was a crash mid-ingest
    rather than a refusal at the point of choosing.

    An unreadable RAM figure (0) answers True: the check exists to warn about a
    machine we measured, never to block one we could not.
    """
    from app.memory_profile import host_ram_gb  # noqa: PLC0415

    available = host_ram_gb() if ram_gb is None else ram_gb
    return available == 0 or available >= profile.min_ram_gb


def models_for_host(
    ram_gb: int | None = None, *, multimodal: bool | None = None
) -> list[ModelProfile]:
    """Registry entries this machine can hold, smallest first.

    Smallest first because the question this answers is "what can I run", and on
    a constrained machine the honest first suggestion is the one that leaves
    room for everything else the pipeline loads -- the embedder, the entity
    model, and a vision model if enrichment is on.
    """
    out = [
        p
        for p in REGISTRY.values()
        if fits_host(p, ram_gb) and (multimodal is None or p.multimodal == multimodal)
    ]
    return sorted(out, key=lambda p: p.resident_bytes)


def oversized_for_host(model_id: str, ram_gb: int | None = None) -> ModelProfile | None:
    """The profile of *model_id* when it does not fit this host, else None.

    Returns the profile rather than a bool so a caller can say how much the
    model wants. An unregistered model returns None -- unmeasured is not the
    same as too large, and the caller that reports it says so (`profile_for`).
    """
    profile = profile_for(model_id)
    if profile is None or fits_host(profile, ram_gb):
        return None
    return profile


def default_chat_model() -> str:
    """The configured on-device default, with its provider prefix."""
    model = get_settings().LITELLM_DEFAULT_MODEL
    return model if "/" in model else f"ollama/{model}"


def default_vision_model() -> str:
    model = get_settings().VISION_MODEL
    return model if "/" in model else f"ollama/{model}"


def configured_generation_override() -> str | None:
    """`LITELLM_GENERATION_MODEL`, or None when unset.

    An override for generation only. It is deliberately read here and nowhere
    else: two services used to read it directly, which is why a model chosen in
    Settings never reached flashcard generation.
    """
    model = get_settings().LITELLM_GENERATION_MODEL
    if not model:
        return None
    return model if "/" in model else f"ollama/{model}"
