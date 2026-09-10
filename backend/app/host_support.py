"""Whether this machine can run local inference at a speed worth shipping.

Luminary's promise is a local model, and a local model on a host with no
accelerator is not a slow version of that promise -- it is a different product.
Measured on an Intel Mac through Docker: `qwen3.5:4b` decodes at ~6 tok/s, a
question takes ~121s end to end and enriching a 128-page book ~143s. Nothing in
the retrieval stack is slow at those sizes; the model is.

**The native installers already refuse the worst case.** `install.sh` and
`bootstrap.sh` both exit on macOS x86_64, because lancedb publishes no macOS
x86_64 wheel. Docker was the remaining door, and it is the one that leads
somewhere worse: Docker Desktop on macOS is a Linux VM under Apple's
Virtualization.framework, and neither Metal nor the Neural Engine is exposed to
it. There is no configuration that fixes that -- unlike Linux with the NVIDIA
container toolkit, where a passed-through GPU makes a container a first-class
host. So the check is for the accelerator, never for Docker: a container with a
GPU passes, and a bare-metal box without one does not.
"""

from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# The message every surface shows. One string, because a support policy stated
# two ways is two things to keep true.
UNSUPPORTED_MESSAGE = (
    "This system isn't supported for running local models at a usable speed. "
    "Reading, search, notes and your learner record all work as normal. For "
    "answers and flashcards, add your own API key in Settings \u2014 or wait for "
    "the hosted version of Luminary, which is coming soon."
)


@dataclass(frozen=True)
class HostSupport:
    """The verdict, and the one fact that decided it."""

    supported: bool
    # Machine-readable, for tests and telemetry. None when supported.
    reason: str | None
    # What the host actually is, quoted back so a report is checkable.
    detail: str
    message: str | None


def _in_container() -> bool:
    """Whether this process is inside a container.

    `/.dockerenv` is written by the Docker daemon itself; the cgroup path covers
    podman and the containerd runtimes that do not write it.
    """
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return True
    try:
        return "docker" in Path("/proc/1/cgroup").read_text()
    except OSError:
        return False


def _has_accelerator() -> bool:
    """Whether a device the inference server can actually use is present.

    Deliberately a device check rather than a benchmark: it answers the same way
    before any model is pulled, which is when a user needs to be told. Apple
    Silicon always has Metal. Everywhere else it is an NVIDIA or AMD node, and
    inside a container those are only present when the host passed them through
    -- which is exactly the distinction that separates a fast Linux container
    from Docker Desktop on a Mac.
    """
    if platform.system() == "Darwin":
        # Metal, and only on Apple Silicon. An Intel Mac's integrated or AMD GPU
        # is not a path the local runner uses.
        return platform.machine() in ("arm64", "aarch64")
    if os.environ.get("CUDA_VISIBLE_DEVICES", "").strip() not in ("", "-1"):
        return True
    for node in ("/dev/nvidiactl", "/proc/driver/nvidia/version", "/dev/kfd"):
        if Path(node).exists():
            return True
    return any(Path("/dev").glob("nvidia[0-9]*"))


def local_inference_support() -> HostSupport:
    """Whether local inference on this host is worth offering.

    Three refusals, each from a case that decided it:

    * **macOS on Intel.** No native install exists (no lancedb wheel) and the
      only remaining route, Docker, cannot reach a GPU on any Mac. ~6 tok/s.
    * **A container with no accelerator.** Docker Desktop on macOS, or a
      CPU-only container anywhere. A container *with* a GPU is not refused.
    * **Under the memory floor.** `memory_profile._STANDARD_MIN_RAM_GB` is 16,
      and Docker Desktop hands its VM roughly half the host -- which is how a
      16GB Mac presents as 7GB and swaps rather than refusing.

    A host with an accelerator and enough memory is supported, however it was
    installed. `host_ram_gb()` returns 0 when memory cannot be read, and an
    unreadable box is not called unsupported on that basis alone -- the
    accelerator check already covers the hosts this exists for.
    """
    from app.memory_profile import _STANDARD_MIN_RAM_GB, host_ram_gb  # noqa: PLC0415

    system, machine = platform.system(), platform.machine()
    containerised = _in_container()
    where = f"{system}/{machine}{' in a container' if containerised else ''}"

    if system == "Darwin" and machine not in ("arm64", "aarch64"):
        return HostSupport(False, "intel_mac", where, UNSUPPORTED_MESSAGE)

    if not _has_accelerator():
        reason = "container_without_accelerator" if containerised else "no_accelerator"
        return HostSupport(False, reason, where, UNSUPPORTED_MESSAGE)

    ram = host_ram_gb()
    if 0 < ram < _STANDARD_MIN_RAM_GB:
        return HostSupport(
            False, "under_memory_floor", f"{where}, {ram}GB", UNSUPPORTED_MESSAGE
        )

    return HostSupport(True, None, where, None)
