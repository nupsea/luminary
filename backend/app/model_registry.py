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
#
# 8192 for every entry, and that is now a measurement rather than an inheritance.
# `context_window_for` made per-model windows possible, so the saving was measured
# on qwen3.5:4b (Ollama /api/ps, reproducible to 0 MB across repeats):
#
#   num_ctx 8192 -> 3.21GB   num_ctx 6144 -> 3.15GB   num_ctx 4096 -> 3.00GB
#
# Shrinking to 6144 saves 60MB -- 0.7% of an 8GB machine -- and cuts the flashcard
# path's headroom from ~3,800 tokens to ~1,700. The only saving worth having
# (210MB) is at 4096, which does not hold the largest prompt at all: ~3,177 tokens
# of prompt plus ~1,200 of output against a 4,096 window, and Ollama truncates
# rather than erroring. So no model gets a smaller window, and
# `tests/test_window_fits_the_largest_prompt.py` fails any entry that tries.
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
        # Measured 2026-08-18, not read off the capability list: on real library
        # figures it named the root of a decision tree correctly and identified an
        # Intel SDM operand-encoding table as x86 with the right field count, and
        # `/api/ps` reported 3.21GB resident WITH an image loaded -- the same as
        # its text footprint. This is what lets one model fill all four roles on an
        # 8GB host, where the 6.81GB vision default cannot be resident at all.
        multimodal=True,
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
        # Capable, and measurably the worst of the three at it: on the same two
        # library figures it called a decision tree "a Boolean logic circuit with
        # addition and subtraction gates" (reading the +/- leaves as operators) and
        # attributed an Intel SDM page to an "ARM Cortex-M4". It is 4x faster than
        # the others because it answers short and wrong. Marked multimodal because
        # the flag describes capability; `vision_preference` is what ranks it last.
        multimodal=True,
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


def context_window_for(model_id: str) -> int:
    """The one context window in force for *model_id* (I-27).

    I-27 has two halves. The rule -- exactly one window per loaded model, because
    Ollama keys a loaded runner on `num_ctx` and a differing call reloads
    llama-server -- has been enforced since it was written. The other half, that
    the *value* is a property of the model and is read from its profile, was never
    built: `usable_context` sat on every entry unread while one global
    `OLLAMA_NUM_CTX` was in force for every model at once. That is why a more
    capable model could not be given a larger window without giving it to
    everything, and why a smaller model could not be given a smaller one to save
    the KV cache it does not need.

    Resolving from the model rather than the call site is *stronger* than the
    global constant, not weaker: the window is now a pure function of the model,
    so two call sites cannot disagree about it even by accident.

    An unregistered model falls back to `OLLAMA_NUM_CTX`. A user may point
    Settings at any model Ollama holds, and refusing to answer is worse than
    answering with the deployment default.
    """
    profile = profile_for(model_id)
    if profile is not None:
        return profile.usable_context
    return get_settings().OLLAMA_NUM_CTX


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


# Text quality, best first, from the structural matrix. `qwen2.5:14b-instruct`
# led routing 0.9655 against llama3.2's 0.8621 (2026-08-16); `qwen3.5:4b` led
# llama3.2 on all three metrics of the 8GB-class run (routing 0.8966 vs 0.8621,
# card_reject_rate 0.0278 vs 0.0463, generation_rate 1.0000 vs 0.9714). Single
# runs each, which is why this ranks a default and does not gate a swap.
#
# llama3.2 sat at the top of this list by inheritance: it was chosen on an HHEM
# faithfulness comparison, and a cross-model HHEM delta is a style artifact that
# may not decide a model. Nothing re-examined it until now.
TEXT_PREFERENCE: tuple[str, ...] = (
    "ollama/qwen2.5:14b-instruct",
    "ollama/qwen3.5:4b",
    "ollama/llama3.2",
)

# A resident set takes at most half the machine. That is the repo's own per-model
# rule (`min_ram_gb` is twice the resident size) applied to the set instead of the
# member, because two models break the assumption the per-model rule rests on --
# "the other half carries the OS, the backend's 4.7GB ingest peak, the embedder
# and the entity model" is a budget for everything else, and it does not double
# when a second model loads. Measured consequence: `qwen3.5:4b` + the 6.81GB
# reader is 10.02GB, which is 63% of a 16GB machine and 92% once the backend peak
# is counted. It fits at 24GB and not before.
_RESIDENT_SET_FRACTION = 0.5


def fits_together(models: tuple[ModelProfile, ...], ram_gb: int | None = None) -> bool:
    """Whether this whole set can be resident at once on this machine."""
    from app.memory_profile import host_ram_gb  # noqa: PLC0415

    ram = host_ram_gb() if ram_gb is None else ram_gb
    if ram == 0:
        return len(models) <= 1  # unmeasurable machine: assume it is small
    total = sum(m.resident_bytes for m in models)
    return total <= ram * _GB * _RESIDENT_SET_FRACTION


def recommended_assignment(ram_gb: int | None = None) -> tuple[str, str] | None:
    """(text model, vision model) -- the best pair this machine can actually hold.

    Text and vision cannot be chosen separately, which is the trap this exists to
    avoid: the strongest text model is not multimodal, so picking it first can
    leave vision with no model the host can also hold. On a 24GB machine
    `qwen2.5:14b-instruct` fits on its own and leaves nothing for a reader, and
    the honest answer there is a smaller text model plus a real one.

    An enumeration rather than an optimisation. The candidate space is a handful
    of pairs, the preference order is measured and written down
    (`TEXT_PREFERENCE`, `VISION_PREFERENCE`), and a reader can check the result by
    eye -- which a solver's answer would not allow.
    """
    for text_id in TEXT_PREFERENCE:
        text = REGISTRY.get(text_id)
        if text is None or not fits_host(text, ram_gb):
            continue
        for vision_id in VISION_PREFERENCE:
            vision = REGISTRY.get(vision_id)
            if vision is None or not fits_host(vision, ram_gb):
                continue
            models = (text,) if vision_id == text_id else (text, vision)
            if fits_together(models, ram_gb):
                return text_id, vision_id
    return None


# Where one model must serve every role, this is the order to try. It is the
# text ranking from the P6 8GB-class run (`qwen3.5:4b` led card_reject_rate
# 0.0278 vs gemma3's 0.1161 and generation_rate 1.0000 vs 0.9238) intersected
# with the vision ranking above, which put the same model first. The two
# independent measurements agree, which is why there is no trade-off to weigh.
GENERALIST_PREFERENCE: tuple[str, ...] = (
    "ollama/qwen3.5:4b",
    "ollama/gemma3:4b",
)


def _multimodal_ranked(
    preference: tuple[str, ...], ram_gb: int | None = None
) -> list[ModelProfile]:
    """Multimodal models this host can hold, ranked by a measured preference.

    Unranked entries sort last by size: a multimodal model nobody has measured is
    not one to hand a figure to ahead of one that has been.
    """
    fitting = [p for p in REGISTRY.values() if p.multimodal and fits_host(p, ram_gb)]
    return sorted(
        fitting,
        key=lambda p: (
            preference.index(p.id) if p.id in preference else len(preference),
            p.resident_bytes,
        ),
    )


def generalist_candidates(ram_gb: int | None = None) -> list[ModelProfile]:
    """Models that can fill *every* role alone on this host, best measured first.

    A profile that may keep one model resident needs one model that does text and
    reads figures. Without this an 8GB host resolved chat to a text-only default
    and vision to a second model it had no room for -- two models on a machine
    allowed one, which is not a configuration at all.
    """
    return _multimodal_ranked(GENERALIST_PREFERENCE, ram_gb)


def _with_provider_prefix(model: str) -> str:
    return model if "/" in model else f"ollama/{model}"


def configured_chat_model() -> str:
    """The chat model as configured, before the host narrows it.

    The pre-narrowing value is what makes "is the model in play the one that was
    asked for" answerable. `default_chat_model()` cannot answer it: it *is* the
    narrowed value.
    """
    return _with_provider_prefix(get_settings().LITELLM_DEFAULT_MODEL)


def configured_vision_model() -> str:
    """The vision model as configured, before the host narrows it."""
    return _with_provider_prefix(get_settings().VISION_MODEL)


def _named_by_a_human(field: str) -> bool:
    """Whether a human set *field*, rather than it carrying the shipped default.

    `model_fields_set` is pydantic's own record of which fields a source
    supplied, so this separates `.env` naming a model from the field default
    happening to be the same string -- which a value comparison cannot do.
    """
    return field in get_settings().model_fields_set


def _resolve_chat_model() -> tuple[str, str | None]:
    """(model, why the configured one was overruled) -- None when it was kept.

    The reason is returned rather than logged because the promise in the
    docstrings below is that a user who configures an oversized model is *told*.
    Narrowing silently and reporting nothing is how a machine ends up running a
    model its owner did not pick and cannot see.
    """
    from app.memory_profile import max_resident_models  # noqa: PLC0415

    configured = configured_chat_model()
    profile = profile_for(configured)

    if profile is None:
        return configured, None  # unregistered: nothing measured to narrow it with

    if max_resident_models() <= 1:
        # One model has to do everything, so it has to be able to read a figure.
        if fits_host(profile) and profile.multimodal:
            return configured, None
        candidates = generalist_candidates()
        if not candidates:
            return configured, None
        why = "does not fit this host" if not fits_host(profile) else "cannot read figures"
        return candidates[0].id, (
            f"this profile keeps one model resident and {configured} {why}"
        )

    # Room for two. On a host large enough to hold the strongest text model
    # *alongside* a reader, use it -- that is what the extra memory is for, and
    # the shipped default is sized for the machine that cannot. The pair is
    # chosen together (`recommended_assignment`) because the strongest text model
    # is not multimodal: picking it alone can leave vision with nothing that fits.
    #
    # Only when nobody named a model. Upgrading a *default* is a decision made on
    # the user's behalf in the absence of one; doing it over an explicit choice is
    # an overrule, and it was silent -- `.env` pinning `llama3.2` on a 32GB host
    # ran a 9.67GB model instead, three times slower, with `narrowed_defaults`
    # empty and a clean bill of health. A pin is a preference, not a starting bid.
    recommended = recommended_assignment()
    if recommended is not None and not _named_by_a_human("LITELLM_DEFAULT_MODEL"):
        text_id, _ = recommended
        if _text_rank(text_id) < _text_rank(configured):
            # An upgrade, not an overrule: the host can hold something stronger.
            return text_id, None
    if fits_host(profile):
        return configured, None
    # Ranked, not `REGISTRY.values()[0]`. Dict order put `llama3.2` first, so a
    # host too small for the configured model fell back to the model this whole
    # selection scheme exists to stop shipping -- invisible on a large dev box
    # and the default on a 16GB CI runner.
    fitting = [
        REGISTRY[model_id]
        for model_id in TEXT_PREFERENCE
        if model_id in REGISTRY and fits_host(REGISTRY[model_id])
    ]
    if not fitting:
        return configured, None
    return fitting[0].id, f"{configured} does not fit this host"


def default_chat_model() -> str:
    """The on-device default, narrowed by what this machine can actually run.

    Host-aware for the same reason `default_vision_model` is: the configured
    default is a deployment decision made without knowing the machine, and on a
    host that may keep only one model resident it has to be a model that can
    serve every role. Shipping `llama3.2` there left vision needing a second
    model the host could not hold.

    When this overrules a configured model, `narrowed_defaults()` carries the
    reason and `residency_report()` surfaces it.
    """
    return _resolve_chat_model()[0]


def _text_rank(model_id: str) -> int:
    """Where a model sits in the measured text order; unranked models sort last."""
    return (
        TEXT_PREFERENCE.index(model_id)
        if model_id in TEXT_PREFERENCE
        else len(TEXT_PREFERENCE)
    )


# Vision quality is measured, not inferred from the capability list, and it does
# not track size. Ranked by what each model did on real library figures
# (2026-08-18): `qwen3.5:4b` read a decision tree's root and an Intel operand
# table correctly at 3.21GB; `qwen2.5vl:7b` was correct on structure but invented
# mnemonic expansions, at 6.81GB; `gemma3:4b` called a decision tree a Boolean
# circuit and an Intel manual page ARM. Lower ranks first.
VISION_PREFERENCE: tuple[str, ...] = (
    "ollama/qwen3.5:4b",
    "ollama/qwen2.5vl:7b",
    "ollama/gemma3:4b",
)


def vision_candidates(ram_gb: int | None = None) -> list[ModelProfile]:
    """Multimodal models this machine can hold, best measured reader first.

    Ranked separately from `generalist_candidates`: a dedicated VLM can outrank a
    generalist at reading a figure while never being a candidate to also answer
    every text question.
    """
    return _multimodal_ranked(VISION_PREFERENCE, ram_gb)


def _resolve_vision_model() -> tuple[str, str | None]:
    """(model, why the configured one was overruled) -- None when it was kept."""
    configured = configured_vision_model()
    profile = profile_for(configured)
    if profile is None or fits_host(profile):
        return configured, None
    candidates = vision_candidates()
    if not candidates:
        return configured, None
    return candidates[0].id, f"{configured} does not fit this host"


def default_vision_model() -> str:
    """The model that reads figures when nobody has chosen one.

    Host-aware, because the configured default weighs 6.81GB and asks for 16GB:
    on an 8GB laptop it cannot be resident at all, so the vision role had *no*
    feasible model and the whole profile had no feasible assignment. Falling back
    to a fitting multimodal model is what makes that machine work.

    When this overrules a configured model, `narrowed_defaults()` carries the
    reason and `residency_report()` surfaces it.
    """
    return _resolve_vision_model()[0]


def default_chat_model_reason() -> str | None:
    """Why this module overruled the configured chat model, else None.

    Only this module's half of the answer. The router narrows again, on whether a
    pair can be resident together, so a report built from this alone described a
    machine that does not exist -- `model_router.narrowed_defaults()` is what
    compares the model asked for against the model that actually resolves.
    """
    return _resolve_chat_model()[1]


def default_vision_model_reason() -> str | None:
    """Why this module overruled the configured vision model, else None."""
    return _resolve_vision_model()[1]


def configured_factuality_checker() -> str:
    """The model that checks whether a generated card's answer follows from its
    passage, or "" when none is configured.

    Read here rather than in the service for the same reason as every other model
    id: one module owns "which model", so a change reaches every call site or
    none. `flashcard_factuality.factuality_model` re-exports this.
    """
    return (get_settings().FLASHCARD_FACTUALITY_MODEL or "").strip()


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
