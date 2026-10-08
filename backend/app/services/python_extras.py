"""Optional Python packages installed after the app, and the model weights they run.

Installed with ``pip --target`` into the extras directory rather than the
bundle's own site-packages: that tree is read-only and code-signed, and writing
to it would invalidate the signature.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import importlib.util
import shutil
import site
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import get_settings

if TYPE_CHECKING:
    from app.services.components import Component


def extras_dir() -> Path:
    """Where user-installed Python packages live: writable, and outside the bundle."""
    return Path(get_settings().DATA_DIR).expanduser() / "extras"


def activate_extras() -> bool:
    """Put user-installed packages on sys.path. Safe to call more than once."""
    target = extras_dir()
    if not target.is_dir():
        return False
    path = str(target)
    if path not in sys.path:
        site.addsitedir(path)
        # addsitedir appends, so a stale copy of something already bundled
        # cannot shadow it -- extras only ever add, never override.
        importlib.invalidate_caches()
    return True


def _whisper_cached() -> bool:
    from app.services.audio_transcriber import weights_cached  # noqa: PLC0415

    return weights_cached()


def _whisper_fetch() -> None:
    from app.services.audio_transcriber import fetch_weights  # noqa: PLC0415

    fetch_weights()


# An extra whose package runs a model: (weights on disk?, download them).
# The install downloads; the loader never does.
EXTRA_WEIGHTS = {"transcription": (_whisper_cached, _whisper_fetch)}


def pins_met(comp: Component) -> bool:
    """Every `name==version` in *comp.packages* is the version that imports."""
    for requirement in comp.packages:
        name, _, version = requirement.partition("==")
        if not version:
            continue
        try:
            if importlib.metadata.version(name) != version:
                return False
        except importlib.metadata.PackageNotFoundError:
            return False
    return True


def packages_present(comp: Component) -> bool:
    """A mismatched version reads as absent, so the install is offered and replaces it."""
    activate_extras()
    return importlib.util.find_spec(comp.ref) is not None and pins_met(comp)


def extra_installed(comp: Component) -> bool:
    if not packages_present(comp):
        return False
    weights = EXTRA_WEIGHTS.get(comp.id)
    return weights is None or weights[0]()


def drop_stale_metadata(target: Path, packages: tuple[str, ...]) -> None:
    """Remove other versions' dist-info of pinned packages.

    `pip --target --upgrade` replaces package folders but keeps an old dist-info,
    which `importlib.metadata` may still read, so the pin check would never pass.
    """
    for requirement in packages:
        name, _, version = requirement.partition("==")
        if not version:
            continue
        stem = name.replace("-", "_").lower()
        for info in target.glob("*.dist-info"):
            dist, _, rest = info.name[: -len(".dist-info")].partition("-")
            if dist.lower() == stem and rest != version:
                shutil.rmtree(info, ignore_errors=True)


async def install_python_extra(comp: Component) -> AsyncIterator[dict]:
    """Install the packages if missing, then the model weights they run."""
    # A source install has the packages from `uv sync` and no pip; only the weights may be missing.
    if not packages_present(comp):
        async for event in _pip_install(comp):
            yield event
            if event["state"] == "failed":
                return

    if weights := EXTRA_WEIGHTS.get(comp.id):
        yield {"state": "downloading", "detail": f"Downloading the {comp.label} model"}
        try:
            await asyncio.to_thread(weights[1])
        except Exception as exc:
            yield {"state": "failed", "detail": f"model download failed: {str(exc)[:300]}"}
            return
    yield {"state": "ready", "detail": comp.label}


async def _pip_install(comp: Component) -> AsyncIterator[dict]:
    """pip into the extras directory; the desktop bundle ships pip, a uv venv does not."""
    if importlib.util.find_spec("pip") is None:
        yield {
            "state": "failed",
            "detail": "This Python has no pip. In a source checkout, run "
            "`uv sync --group media` in backend/, then restart Luminary.",
        }
        return
    target = extras_dir()
    target.mkdir(parents=True, exist_ok=True)
    drop_stale_metadata(target, comp.packages)

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--target",
        str(target),
        "--no-input",
        "--disable-pip-version-check",
        *comp.packages,
    ]
    yield {"state": "downloading", "detail": f"Installing {', '.join(comp.packages)}"}

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    tail: list[str] = []
    assert proc.stdout is not None  # noqa: S101
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").rstrip()
        if not line:
            continue
        tail = [*tail[-4:], line]
        yield {"state": "downloading", "detail": line[:160]}
    await proc.wait()

    if proc.returncode != 0:
        yield {"state": "failed", "detail": " / ".join(tail)[:400] or "pip failed"}
        return

    activate_extras()
    if importlib.util.find_spec(comp.ref) is None:
        yield {"state": "failed", "detail": f"{comp.ref} still not importable after install"}
