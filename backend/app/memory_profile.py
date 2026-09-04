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
# A floor machine runs ONE model -- `qwen3.5:4b` at 3.21GB serving chat and
# figures alike -- plus the backend's measured 3.19GB ingest peak: 6.40GB, 40%.
# It is not sized for a pair, and does not get one: `fits_together` budgets a
# resident set at half the machine, and the 10.02GB pair exceeds 8GB. Below the
# floor the profile is unchanged and the mismatch is reported instead.
_STANDARD_MIN_RAM_GB = 16

# Above this, not at it: a 24GB machine stays `standard`. The 9.67GB text model
# plus the 6.81GB reader is 16.48GB, which is over half of 24GB and under half of
# 32GB, so 24GB is the last size that runs the small text model.
_PERFORMANCE_MIN_RAM_GB = 24

# How many models may stay resident at once. Mirrors OLLAMA_MAX_LOADED_MODELS as
# the installer sets it; each loaded model gets its own runner and its own KV
# cache (I-31), so this is a memory bound, not a concurrency one.
#
# Two, and the case that decides it is at the top of the band, not at the floor.
# `standard` runs to 24GB, where `fits_together` budgets a resident set at half
# the machine -- 12GB against the 10.02GB pair (`qwen3.5:4b` 3.21GB plus
# `qwen2.5vl:7b` 6.81GB, from Ollama's `/api/ps` with both loaded), so the pair
# fits and a configured reader is kept. At one slot that host was narrowed to a
# shared model and told "this profile keeps one model resident", which is false
# about a machine with room for two.
#
# **At the 16GB floor this count decides nothing.** Half of 16GB is 8GB, the pair
# is 10.02GB, and `model_router` refuses it at either setting -- verified by
# resolving both ways. The budget is what protects a small desktop; the runner
# count is a permission, and a permission is not a bound.
#
# **Residency is what Ollama reports, never a process RSS.** One slot shipped
# here briefly on figures ~30% high, built by subtracting the backend's RSS from
# the run's peak RSS and calling the remainder a model. `mem_profile.py`'s
# docstring names that trap: on unified memory the runner's RSS double-counts
# weights it maps, so RSS and Ollama's accounting disagree and only the latter is
# residency. The same pass read `peak_ollama_reported_mb` -- an MB field -- as GB.
#
# Whatever this says, `supervisor.rs` must say too: it sizes the bundled DMG,
# which has no install step, and a backend resolving a pair against a runtime
# permitted one model evicts on every switch between them (I-31, I-39).
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

    Two bands. 16GB is the floor and gets two resident models with the small
    text model; above 24GB, two with the large one. A machine under the floor
    gets `standard` too -- the same behaviour plus a reported mismatch, rather
    than a narrowed profile nobody tuned.

    `performance` used to be unreachable automatically, on the grounds that it
    raises parallelism past what a single GPU serves well (I-31). It is reachable
    now because above 24GB the memory it unlocks is real -- the 9.67GB text model
    and a reader fit together -- and the parallelism no longer rides along with
    it: every install path sizes `OLLAMA_NUM_PARALLEL` from RAM rather than from
    the profile name, so this band decides the model map and nothing else.
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
