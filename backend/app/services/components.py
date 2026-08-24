"""Optional pieces the user installs after the app itself is installed.

Two problems this solves.

The first is weight: a bundle that shipped every model would be tens of
gigabytes, and most users need none of them. Only what a given person actually
uses gets downloaded, on their say-so.

The second is licensing. Luminary ships under Apache-2.0, so anything with a
copyleft licence cannot travel inside the installer. Fetching it at runtime, at
the user's explicit request and onto their own machine, keeps the distributed
artifact clean -- which is why ``licence`` is part of the catalogue and is shown
before an install starts, not buried in a notices file.

Model names are **not** decided here. `model_registry` holds the measured
footprints and the per-profile preference order, and the two model entries below
resolve their tag and size from it. When this file carried its own names it
offered `llama3.2` on a machine whose installer had pulled the profile's model,
so the setup screen and the installer disagreed about what the app runs.
"""

import asyncio
import importlib
import importlib.util
import json
import logging
import os
import shutil
import site
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from pathlib import Path

import httpx

from app.config import get_settings
from app.model_registry import (
    REGISTRY,
    default_chat_model,
    default_vision_model,
    profile_for,
)

logger = logging.getLogger(__name__)

Kind = str  # "ollama_model" | "tool"


@dataclass(frozen=True)
class Component:
    id: str
    label: str
    description: str
    kind: Kind
    # Approximate download size, for the UI to set expectations before starting.
    size_bytes: int
    licence: str
    # Identifier in the component's own namespace: an Ollama model tag, an
    # executable name, or the module a python_extra makes importable.
    ref: str = ""
    # For python_extra: the requirements to install.
    packages: tuple[str, ...] = field(default_factory=tuple)
    default: bool = False
    enables: tuple[str, ...] = field(default_factory=tuple)


_GB = 1024**3
_MB = 1024**2


def _registry_tag(model_id: str) -> str:
    """`ollama/qwen3.5:4b` -> `qwen3.5:4b`, the tag `ollama pull` takes."""
    return model_id.split("/", 1)[-1]


def _registry_size(model_id: str, fallback: int) -> int:
    """Measured resident bytes, which is what the user waits for and pays RAM for.

    The fallback covers a configured model the registry has never measured -- a
    third-party or hand-picked tag. Showing a wrong-but-plausible size is better
    than showing none, and `models_for_host` already refuses to plan around an
    unmeasured model.
    """
    profile = profile_for(model_id)
    return profile.resident_bytes if profile is not None else fallback


def _registry_licence(model_id: str) -> str:
    """Shown before a download starts, so an unmeasured model must not claim one."""
    profile = profile_for(model_id)
    return profile.licence if profile is not None else "See the model's own licence"


def catalogue() -> tuple[Component, ...]:
    """What the user can install, resolved against the registry *now*.

    Built per call rather than held as a module constant. As a constant its two
    model entries froze `get_settings()` and `host_ram_gb()` at import time, so
    the catalogue advertised -- and installed -- whatever those read the moment
    this module was first imported. Both are cached in-process, so it seldom
    drifted in the app and was correspondingly hard to see; what it did do was
    let import order decide what the tests measured, and a suite that pins the
    model knobs in a fixture was still asserting against a catalogue built
    before the pin.
    """
    return (
        Component(
            id="chat_model",
            label="Chat model",
            description="Answers questions and generates flashcards, entirely on this machine.",
            kind="ollama_model",
            ref=_registry_tag(default_chat_model()),
            size_bytes=_registry_size(default_chat_model(), 2 * _GB),
            licence=_registry_licence(default_chat_model()),
            default=True,
            enables=("Ask", "Flashcard generation", "Summaries"),
        ),
        Component(
            id="vision_model",
            label="Vision model",
            description="Reads figures, diagrams and screenshots inside your documents.",
            kind="ollama_model",
            ref=_registry_tag(default_vision_model()),
            size_bytes=_registry_size(default_vision_model(), 6 * _GB),
            licence=_registry_licence(default_vision_model()),
            enables=("Figure captioning", "Diagram understanding"),
        ),
        Component(
            id="transcription",
            label="Speech to text",
            description="Transcribes audio and video into searchable, studyable text.",
            kind="python_extra",
            ref="faster_whisper",
            packages=("faster-whisper>=1.2.1",),
            size_bytes=350 * _MB,
            # faster-whisper pulls PyAV, whose wheels bundle libx264 and libx265.
            # Apache-2.0 Luminary cannot ship those, so this is fetched from PyPI
            # on request instead of travelling inside the installer.
            licence="GPL-2.0-or-later components (not distributed with Luminary)",
            enables=("Audio ingestion", "Video ingestion", "YouTube transcription"),
        ),
        Component(
            id="ffmpeg",
            label="Audio and video support",
            description="Required to ingest MP4 video and to transcribe YouTube audio.",
            kind="tool",
            ref="ffmpeg",
            size_bytes=80 * _MB,
            # FFmpeg builds that carry x264/x265 are GPL, which is why this is never
            # part of the installer and is only ever fetched on request.
            licence="GPL-2.0-or-later (not distributed with Luminary)",
            enables=("MP4 ingestion", "YouTube transcription"),
        ),
    )


# The id a registry model gets when it is not one of the catalogue's current
# picks. Every install path re-looks-up by id -- `install_component` and
# `remove_component` both call `get_component(component_id)` and act on the
# `ref` they find there -- so a synthesized component that borrowed a catalogue
# id named one model and installed another: the setup screen reported
# `qwen2.5vl:7b` missing and its install button pulled the generalist, after
# which `requeue_skipped_jobs()` skipped the job again, forever.
_MODEL_ID_PREFIX = "model:"


def get_component(component_id: str) -> Component | None:
    for comp in catalogue():
        if comp.id == component_id:
            return comp
    if component_id.startswith(_MODEL_ID_PREFIX):
        return _component_for_registry_model(component_id[len(_MODEL_ID_PREFIX) :])
    return None


def _bare_model_name(model: str) -> str:
    """Strip the LiteLLM provider prefix and a `:latest` tag."""
    name = model.split("/", 1)[-1].strip()
    return name[: -len(":latest")] if name.endswith(":latest") else name


def _component_for_registry_model(wanted: str) -> Component | None:
    """An installable component for a registry model, or None if unknown.

    Built around the model asked for rather than the role's default, because the
    returned component is what gets pulled. Its id round-trips through
    `get_component`, which is what makes the component that *names* a model the
    component that *installs* it.
    """
    for model_id, known in REGISTRY.items():
        bare = _bare_model_name(model_id)
        if not (wanted == bare or bare.startswith(f"{wanted}:") or wanted.startswith(f"{bare}:")):
            continue
        template = get_component("vision_model" if known.multimodal else "chat_model")
        if template is None:  # unreachable: both ids are catalogue entries
            return None
        return replace(
            template,
            id=f"{_MODEL_ID_PREFIX}{bare}",
            ref=bare,
            size_bytes=known.resident_bytes,
            licence=known.licence,
            default=False,
        )
    return None


def component_for_model(model: str) -> Component | None:
    """The catalogue entry a model name belongs to, if the user can install it.

    Turns a failure that names a model into the action that fixes it.
    """
    wanted = _bare_model_name(model)
    if not wanted:
        return None
    for comp in catalogue():
        if comp.kind != "ollama_model":
            continue
        ref = _bare_model_name(comp.ref)
        # Untagged matches tagged: Ollama reports a missing `qwen2.5vl:7b` as
        # `qwen2.5vl`.
        if wanted == ref or ref.startswith(f"{wanted}:") or wanted.startswith(f"{ref}:"):
            return comp

    # Not the catalogue's current pick, but a model the registry knows: the user
    # configured it, or a failure named it. The catalogue entries follow the host,
    # so on a machine that resolves vision to the generalist, `qwen2.5vl:7b` --
    # which the user may have chosen and Ollama may be complaining about -- matched
    # nothing and the UI offered no way to install it.
    return _component_for_registry_model(wanted)


def tool_bin_dir() -> Path:
    """Where user-installed executables live: writable, and outside the bundle."""
    return Path(get_settings().DATA_DIR).expanduser() / "bin"


def extras_dir() -> Path:
    """Where user-installed Python packages live.

    Outside the bundle, which is read-only and code-signed -- writing into it
    would break the signature even if the permissions allowed it.
    """
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


# Where the package managers put things, searched after PATH.
#
# The bundled app's PATH is its own runtime plus `/usr/bin:/bin` -- a login
# shell's PATH never reaches it. So a user who had already run
# `brew install ffmpeg` was told by Luminary to run `brew install ffmpeg`: the
# binary sat at /opt/homebrew/bin/ffmpeg and `shutil.which` could not see it.
# Homebrew on Apple silicon, Homebrew on Intel, MacPorts, and the usual Linux
# prefixes.
_WELL_KNOWN_TOOL_DIRS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/opt/local/bin",
    "/usr/bin",
    "/bin",
    "/snap/bin",
)


def running_in_container() -> bool:
    """Whether this process is inside a container.

    This changes what a user can be told to do, not what the app does. A
    containerised backend cannot see the host's PATH, so `brew install ffmpeg`
    is advice that succeeds on the host and changes nothing here -- the user
    follows it and hits the same wall, which is the exact trap the media
    error message was rewritten once already to avoid.
    """
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


def resolve_tool(name: str) -> str | None:
    """Find a tool the user installed, falling back to whatever is on PATH.

    The bundled app runs with a minimal PATH and cannot rely on a user's shell
    environment, so the app-managed directory is searched first and the standard
    install prefixes are searched last.
    """
    candidate = tool_bin_dir() / name
    if candidate.is_file():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    for directory in _WELL_KNOWN_TOOL_DIRS:
        candidate = Path(directory) / name
        # Executable, not merely present: a name that cannot be run is not a
        # find, and reporting one turns a clear "not installed" into a failure
        # at the point of use.
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


async def _installed_ollama_models() -> set[str]:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return set()
    return {m.get("name", "") for m in data.get("models", [])}


async def component_status() -> list[dict]:
    installed_models = await _installed_ollama_models()

    out = []
    for comp in catalogue():
        if comp.kind == "ollama_model":
            # Ollama reports tags as "name:tag"; a bare ref means ":latest".
            ref = comp.ref if ":" in comp.ref else f"{comp.ref}:latest"
            installed = ref in installed_models or comp.ref in installed_models
        elif comp.kind == "python_extra":
            activate_extras()
            installed = importlib.util.find_spec(comp.ref) is not None
        else:
            installed = resolve_tool(comp.ref) is not None

        out.append(
            {
                "id": comp.id,
                "label": comp.label,
                "description": comp.description,
                "kind": comp.kind,
                "ref": comp.ref,
                "size_bytes": comp.size_bytes,
                "licence": comp.licence,
                "default": comp.default,
                "enables": list(comp.enables),
                "installed": installed,
            }
        )
    return out


async def capabilities() -> dict:
    """What this install can actually ingest right now.

    Derived here rather than in the UI so that the mapping from component to
    feature lives in one place: video needs both a transcriber and ffmpeg, a
    YouTube URL needs yt-dlp on top of those, and none of that is obvious from
    a component list.
    """
    status = {c["id"]: c["installed"] for c in await component_status()}
    transcribe = status.get("transcription", False)
    ffmpeg = status.get("ffmpeg", False)
    ytdlp = resolve_tool("yt-dlp") is not None
    article = importlib.util.find_spec("trafilatura") is not None

    def cap(available: bool, needs: tuple[str, ...]) -> dict:
        return {"available": available, "requires": list(needs) if not available else []}

    missing_media = tuple(
        name for name, ok in (("transcription", transcribe), ("ffmpeg", ffmpeg)) if not ok
    )
    return {
        "audio_ingest": cap(transcribe, ("transcription",)),
        "video_ingest": cap(transcribe and ffmpeg, missing_media),
        "youtube_ingest": cap(transcribe and ffmpeg and ytdlp, missing_media),
        "web_ingest": cap(article, ()),
        "vision": cap(status.get("vision_model", False), ("vision_model",)),
        "chat": cap(status.get("chat_model", False), ("chat_model",)),
    }


async def install_ollama_model(model: str) -> AsyncIterator[dict]:
    """Pull a model, yielding progress events.

    Uses Ollama's HTTP API rather than spawning the `ollama` binary. The
    subprocess route needed the binary on PATH, which a GUI-launched process
    does not get, and it gave line-oriented text instead of byte counts.
    """
    settings = get_settings()
    payload = {"model": model, "stream": True}

    timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client, client.stream(
        "POST", f"{settings.OLLAMA_URL}/api/pull", json=payload
    ) as resp:
        if resp.status_code != 200:
            body = (await resp.aread()).decode(errors="replace")[:200]
            yield {"state": "failed", "detail": f"{resp.status_code}: {body}"}
            return

        async for raw in resp.aiter_lines():
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue

            if error := event.get("error"):
                yield {"state": "failed", "detail": error}
                return

            yield {
                "state": "downloading",
                "detail": event.get("status", ""),
                "completed_bytes": int(event.get("completed") or 0),
                "total_bytes": int(event.get("total") or 0),
            }

    yield {"state": "ready", "detail": model}


async def remove_ollama_model(model: str) -> None:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            "DELETE", f"{settings.OLLAMA_URL}/api/delete", json={"model": model}
        )
        resp.raise_for_status()


async def install_python_extra(comp: Component) -> AsyncIterator[dict]:
    """Install packages into the extras directory using the bundled interpreter.

    ``--target`` rather than the bundle's own site-packages: that tree is
    read-only and code-signed, and writing to it would invalidate the signature.
    """
    target = extras_dir()
    target.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "pip", "install",
        "--upgrade", "--target", str(target), "--no-input", "--disable-pip-version-check",
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
        return
    yield {"state": "ready", "detail": comp.label}


async def install_component(component_id: str) -> AsyncIterator[dict]:
    comp = get_component(component_id)
    if comp is None:
        yield {"state": "failed", "detail": f"unknown component: {component_id}"}
        return

    if comp.kind == "ollama_model":
        async for event in install_ollama_model(comp.ref):
            yield event
        return

    if comp.kind == "python_extra":
        async for event in install_python_extra(comp):
            yield event
        return

    # Tools have no automated source yet: a build has to be chosen deliberately
    # because the licence travels with it. Report rather than guess.
    yield {
        "state": "failed",
        "detail": (
            f"{comp.label} has no automatic installer yet. "
            f"Place the `{comp.ref}` binary in {tool_bin_dir()} to enable it."
        ),
    }


async def remove_component(component_id: str) -> None:
    comp = get_component(component_id)
    if comp is None:
        raise ValueError(f"unknown component: {component_id}")
    if comp.kind == "ollama_model":
        await remove_ollama_model(comp.ref)
        return
    if comp.kind == "python_extra":
        # Deliberately not implemented: pip --target has no uninstall, and
        # working out which of the extras directory's files belong to this
        # component means parsing every RECORD. Removing the whole directory
        # would take unrelated components with it.
        raise ValueError(
            f"{comp.label} cannot be removed automatically. "
            f"Delete {extras_dir()} to remove all installed extras."
        )
    path = tool_bin_dir() / comp.ref
    await asyncio.to_thread(path.unlink, True)
