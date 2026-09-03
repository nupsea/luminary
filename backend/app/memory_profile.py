"""How much machine there is, and what that permits.

The registry has carried `min_ram_gb` and `resident_bytes` since P3 and nothing
read them, so a 10GB model was selectable on a machine that cannot hold it and
the first symptom was a crash during ingestion. This is the module that makes
those fields load-bearing.

**Advisory in the backend, authoritative at install time.** `install.sh` and
`supervisor.rs` size `OLLAMA_MAX_LOADED_MODELS` and `OLLAMA_NUM_PARALLEL` from
host RAM and pass the same values to Ollama and to this process; I-31 is
explicit that if the two disagree the extra slots sit idle behind a narrower
semaphore. So nothing here overrides those. What this adds is the half that was
missing: reporting the profile, and answering whether the models a user has
actually selected fit the machine they are on.

Two profiles. **16GB is the supported floor.** A smaller machine still starts --
`profile_suits_host` reports the mismatch and nothing refuses to run -- but it is
not a size the product is tuned for, and pretending otherwise by shipping a
one-model profile produced an experience that fell flat on every OS but the
maintainer's own.

`low` and `public` are accepted as legacy aliases so an installed `.env` keeps
working; both resolve to `standard`.

The RAM thresholds match `install.sh:_default_profile` deliberately: two
detectors that disagree about what machine this is would be worse than one that
is occasionally wrong.
"""

from __future__ import annotations

import functools
import logging
from typing import Literal

from app.config import get_settings

logger = logging.getLogger(__name__)

MemoryProfile = Literal["standard", "performance"]

PROFILES: tuple[MemoryProfile, ...] = ("standard", "performance")

# Names that shipped before the floor moved to 16GB. Keep reading them: an
# installed .env carries one, and failing to start on it would be worse than
# quietly giving that machine the profile it now gets anyway.
_LEGACY_ALIASES = {"public": "standard", "low": "standard"}

# The supported floor, and what `install.sh:_default_profile` sizes against.
# `qwen3.5:4b` plus the 6.81GB reader is 10.02GB, 63% of 16GB before the
# backend's 4.7GB ingest peak -- tight, but it is the size the product is tuned
# for. Below it the profile is unchanged and the mismatch is reported instead.
_STANDARD_MIN_RAM_GB = 16

# Above this, not at it: a 24GB machine stays `standard`. The 9.67GB text model
# plus the 6.81GB reader is 16.48GB, which is over half of 24GB and under half of
# 32GB, so 24GB is the last size that runs the small text model.
_PERFORMANCE_MIN_RAM_GB = 24

# How many models may stay resident at once. Mirrors OLLAMA_MAX_LOADED_MODELS as
# the installer sets it; each loaded model gets its own runner and its own KV
# cache (I-31), so this is a memory bound, not a concurrency one.
MAX_RESIDENT: dict[MemoryProfile, int] = {"standard": 2, "performance": 2}

# What a host must have before a profile is a sensible default for it. Used to
# report a mismatch, never to refuse to start: someone who sets a profile by
# hand has a reason, and a refusing backend is worse than a warning.
PROFILE_MIN_RAM_GB: dict[MemoryProfile, int] = {
    # Tracks `_STANDARD_MIN_RAM_GB`. A 12GB machine now reports a mismatch rather
    # than being silently narrowed to one model, which is the honest signal: it
    # runs, and it is below what this is tuned for.
    "standard": _STANDARD_MIN_RAM_GB,
    # Two models AND wider serving, and where the strongest text model and a
    # reader fit together under the half-the-machine budget.
    "performance": _PERFORMANCE_MIN_RAM_GB,
}


@functools.lru_cache(maxsize=1)
def host_ram_gb() -> int:
    """Physical RAM in whole GB, or 0 when it cannot be read.

    0 is a real answer and is treated as a small machine, exactly as the
    installer does: an unknown box must never be guessed into `standard`.
    """
    try:
        import psutil  # noqa: PLC0415

        return int(psutil.virtual_memory().total / (1024**3))
    except Exception:
        logger.warning("could not read host memory; assuming a small machine")
        return 0


def profile_for_ram(ram_gb: int) -> MemoryProfile:
    """The profile a host of this size gets by default.

    Three bands since 2026-08-18: below 16GB one model, 16-24GB two models with
    the small text model, above 24GB two models with the large one.

    `performance` used to be unreachable automatically, on the grounds that it
    raises parallelism past what a single GPU serves well (I-31). It is reachable
    now because above 24GB the memory it unlocks is real -- the 9.67GB text model
    and a reader fit together -- but the parallelism half of that profile is still
    the part I-31 warns about: each slot costs a full window of KV cache and buys
    nothing past the runtime's serving width. What the band is for is the model
    map; the slot count rides along and is worth revisiting separately.
    """
    if ram_gb > _PERFORMANCE_MIN_RAM_GB:
        return "performance"
    # Never below `standard`: 16GB is the floor, and a smaller machine gets the
    # same behaviour plus the mismatch warning rather than a narrowed one.
    return "standard"


def active_profile() -> MemoryProfile:
    """The profile in force: the configured one, else sized from host RAM."""
    configured = (get_settings().LUMINARY_MEMORY_PROFILE or "").strip().lower()
    configured = _LEGACY_ALIASES.get(configured, configured)
    if configured in PROFILES:
        return configured  # type: ignore[return-value]
    if configured:
        logger.warning(
            "LUMINARY_MEMORY_PROFILE=%r is not one of %s; sizing from host RAM instead",
            configured,
            PROFILES,
        )
    return profile_for_ram(host_ram_gb())


def profile_is_explicit() -> bool:
    """Whether a human chose the profile, rather than it being sized from RAM."""
    configured = (get_settings().LUMINARY_MEMORY_PROFILE or "").strip().lower()
    return _LEGACY_ALIASES.get(configured, configured) in PROFILES


def max_resident_models(profile: MemoryProfile | None = None) -> int:
    return MAX_RESIDENT[profile or active_profile()]


def profile_suits_host(profile: MemoryProfile | None = None) -> bool:
    """Whether the active profile is one this machine can carry.

    False means someone set a profile larger than the hardware — worth saying
    out loud, since the failure it produces is a crash under load rather than
    an error at startup.
    """
    ram = host_ram_gb()
    if ram == 0:
        return True  # unknown: do not cry wolf
    return ram >= PROFILE_MIN_RAM_GB[profile or active_profile()]


def reset_cache() -> None:
    """Forget the detected RAM. For tests, and for nothing else."""
    host_ram_gb.cache_clear()
