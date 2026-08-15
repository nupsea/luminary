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
    # Filled by the model matrix, never authored. Empty means unmeasured.
    accommodations_needed: tuple[str, ...] = field(default_factory=tuple)

    @property
    def resident_gb(self) -> float:
        return round(self.resident_bytes / _GB, 2)


# Keyed by the id LiteLLM is called with, provider prefix included.
REGISTRY: dict[str, ModelProfile] = {
    "ollama/llama3.2": ModelProfile(
        id="ollama/llama3.2",
        licence="Llama 3.2 Community License",
        resident_bytes=2 * _GB,
        min_ram_gb=8,
        usable_context=8192,
        supports_json_schema=False,
        thinking_default=False,
    ),
    "ollama/qwen2.5:14b-instruct": ModelProfile(
        id="ollama/qwen2.5:14b-instruct",
        licence="Apache-2.0",
        resident_bytes=10 * _GB,
        min_ram_gb=24,
        usable_context=32768,
        supports_json_schema=True,
        thinking_default=False,
    ),
    "ollama/qwen2.5vl:7b": ModelProfile(
        id="ollama/qwen2.5vl:7b",
        licence="Apache-2.0",
        resident_bytes=6 * _GB,
        min_ram_gb=16,
        usable_context=32768,
        supports_json_schema=False,
        thinking_default=False,
        multimodal=True,
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
