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

This catalogue is also the single source of truth for model names. They were
previously repeated across config.py, .env.example, three install scripts,
docker-compose.yml, start.sh and the README, with no mechanism keeping them
consistent.
"""

import asyncio
import json
import logging
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.config import get_settings

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
    # Identifier in the component's own namespace (an Ollama model tag, ...).
    ref: str = ""
    default: bool = False
    enables: tuple[str, ...] = field(default_factory=tuple)


_GB = 1024**3
_MB = 1024**2

CATALOGUE: tuple[Component, ...] = (
    Component(
        id="chat_model",
        label="Chat model",
        description="Answers questions and generates flashcards, entirely on this machine.",
        kind="ollama_model",
        ref="llama3.2",
        size_bytes=2 * _GB,
        licence="Llama 3.2 Community License",
        default=True,
        enables=("Ask", "Flashcard generation", "Summaries"),
    ),
    Component(
        id="vision_model",
        label="Vision model",
        description="Reads figures, diagrams and screenshots inside your documents.",
        kind="ollama_model",
        ref="qwen2.5vl:7b",
        size_bytes=6 * _GB,
        licence="Apache-2.0",
        enables=("Figure captioning", "Diagram understanding"),
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

_BY_ID = {c.id: c for c in CATALOGUE}


def get_component(component_id: str) -> Component | None:
    return _BY_ID.get(component_id)


def tool_bin_dir() -> Path:
    """Where user-installed executables live: writable, and outside the bundle."""
    return Path(get_settings().DATA_DIR).expanduser() / "bin"


def resolve_tool(name: str) -> str | None:
    """Find a tool the user installed, falling back to whatever is on PATH.

    The bundled app runs with a minimal PATH and cannot rely on a user's shell
    environment, so the app-managed directory is searched first.
    """
    candidate = tool_bin_dir() / name
    if candidate.is_file():
        return str(candidate)
    return shutil.which(name)


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
    for comp in CATALOGUE:
        if comp.kind == "ollama_model":
            # Ollama reports tags as "name:tag"; a bare ref means ":latest".
            ref = comp.ref if ":" in comp.ref else f"{comp.ref}:latest"
            installed = ref in installed_models or comp.ref in installed_models
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


async def install_ollama_model(model: str) -> AsyncIterator[dict]:
    """Pull a model, yielding progress events.

    Uses Ollama's HTTP API rather than spawning the `ollama` binary. The
    subprocess route needed the binary on PATH, which a GUI-launched process
    does not get, and it gave line-oriented text instead of byte counts.
    """
    settings = get_settings()
    payload = {"model": model, "stream": True}

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
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


async def install_component(component_id: str) -> AsyncIterator[dict]:
    comp = get_component(component_id)
    if comp is None:
        yield {"state": "failed", "detail": f"unknown component: {component_id}"}
        return

    if comp.kind == "ollama_model":
        async for event in install_ollama_model(comp.ref):
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
    path = tool_bin_dir() / comp.ref
    await asyncio.to_thread(path.unlink, True)
