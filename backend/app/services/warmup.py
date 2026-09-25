"""Bringing the local models up, at startup and on retry.

Extracted from the lifespan so a failed first run is recoverable: a transient
network problem used to leave the install permanently degraded, with the only
remedy being to quit and relaunch.

Order matters. Everything not already on disk is fetched first, concurrently,
because downloading is network-bound and needs no lock. Construction then runs
through the loaders unchanged, serialised by MODEL_LOAD_LOCK, reading from the
cache the fetch just filled.
"""

import asyncio
import logging
import time

import httpx

from app.config import get_settings
from app.services import model_keepwarm, model_prefetch, network_errors
from app.services.executors import get_model_executor
from app.services.startup_status import get_startup_status

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()


async def _construct(key: str, label: str, build) -> None:
    status = get_startup_status()
    loop = asyncio.get_running_loop()
    try:
        # Name the artifact, not just the activity: a first run spends minutes
        # here and "Concept extraction" alone does not tell the user that a
        # 1.1GB GLiNER model is what they are waiting on.
        spec = model_prefetch.spec_for(key)
        status.set_state(key, "loading", spec.repo_id if spec else "")
        await loop.run_in_executor(get_model_executor(), build)
        status.set_state(key, "ready")
        logger.info("Warmup: %s ready", label)
    except Exception as exc:
        status.set_state(key, "failed", _friendly(exc))
        logger.warning("Warmup: %s failed: %s", label, exc)


async def _load_embedder() -> None:
    from app.services.embedder import get_embedding_service  # noqa: PLC0415

    await _construct("embedder", "embedding model", get_embedding_service()._load_model)


async def _load_ner() -> None:
    if not get_settings().GLINER_ENABLED:
        get_startup_status().set_state("ner", "skipped", "Turned off in settings")
        return

    from app.services.ner import get_entity_extractor  # noqa: PLC0415

    await _construct("ner", "entity model", get_entity_extractor()._load_model)


async def _load_reranker() -> None:
    from app.database import get_session_factory  # noqa: PLC0415
    from app.services.settings_service import get_rerank_enabled  # noqa: PLC0415

    status = get_startup_status()
    try:
        async with get_session_factory()() as session:
            if not await get_rerank_enabled(session):
                status.set_state("reranker", "skipped", "Reranking is turned off")
                return
    except Exception as exc:
        status.set_state("reranker", "failed", str(exc))
        return

    from app.services.retriever_strategies import _get_reranker  # noqa: PLC0415

    await _construct("reranker", "reranker", _get_reranker()._load)


def _model_not_installed(exc: Exception) -> bool:
    text = str(exc).lower()
    return "not found" in text and "model" in text


def _friendly(exc: Exception, *, engine: bool = False) -> str:
    """A sentence for a person, not a traceback; the detail is logged in full.

    *engine* marks a call to the local model server. Only there may a failed
    connection be blamed on it: a certificate refusal on a model download once
    read "Could not reach the local model server" while that server was fine.
    """
    text = str(exc)
    lowered = text.lower()
    found = network_errors.kind(text)
    if found in ("inspected", "proxy", "dns") or (found and not engine):
        return network_errors.explain(text) or text
    if engine and "connect" in lowered:
        return "Could not reach the local model server."
    if "timeout" in lowered or "timed out" in lowered:
        return "Timed out while starting."
    return text.split("\n", 1)[0][:160]


async def _measure_offload() -> bool:
    """Ask the model server where it put the chat model it just loaded.

    Returns True when it ran on the processor, which makes this host unsupported
    from here on (`host_support.local_inference_support`). A model the server no
    longer lists, or a server that will not say, records nothing.
    """
    from app import host_support  # noqa: PLC0415
    from app.services.model_router import resolve  # noqa: PLC0415

    choice = resolve("chat")
    if not choice.is_local:
        return False
    name = choice.model.removeprefix("ollama/")
    url = get_settings().OLLAMA_URL
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{url}/api/ps")
            resp.raise_for_status()
            loaded = resp.json().get("models") or []
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Warmup: could not read where %s is loaded: %s", name, exc)
        return False

    wanted = {name, f"{name}:latest"}
    entry = next((m for m in loaded if {m.get("name"), m.get("model")} & wanted), None)
    if entry is None:
        return False
    found = host_support.record_offload(
        name, int(entry.get("size") or 0), int(entry.get("size_vram") or 0)
    )
    logger.info(
        "Warmup: %s holds %d of %d bytes on the graphics card", name, found.size_vram, found.size
    )
    # Asked of the verdict rather than read off the measurement, so a deployment
    # that declared its accelerator keeps it and this phase cannot disagree.
    if host_support.local_inference_support().supported:
        return False
    # A model on the processor holds gigabytes of memory for nothing now refused.
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(f"{url}/api/generate", json={"model": name, "keep_alive": 0})
    except httpx.HTTPError:
        pass
    return True


async def _warm_llm() -> None:
    """Fire a tiny generation so the first real question does not pay the load.

    Fails soft: a missing key or an unpulled model must not hold up startup.
    """
    from app.services.llm import get_llm_service  # noqa: PLC0415

    status = get_startup_status()

    async def _one(model: str | None, label: str) -> None:
        interactive = label == "interactive"
        try:
            t0 = time.perf_counter()
            if interactive:
                status.set_state("chat_model", "loading", model or "")
            # Never shorter than a cold load: giving up here closes the
            # connection and Ollama aborts the load it was still doing.
            await get_llm_service().generate(
                "ping", model=model, timeout=get_settings().LLM_WARMUP_TIMEOUT_SECONDS
            )
            elapsed = time.perf_counter() - t0
            if interactive and await _measure_offload():
                from app.host_support import UNSUPPORTED_MESSAGE  # noqa: PLC0415

                status.set_state("chat_model", "unavailable", UNSUPPORTED_MESSAGE)
                logger.warning("Warmup: the chat model ran on the processor; local models off")
                return
            if interactive:
                status.set_state("chat_model", "ready", model or "")
                # The one local generation at start-up that something already
                # times. Whether its cost was a load, start-up contention, or
                # both, it is what getting an answer out of this machine costs,
                # which is what `model_keepwarm` gates on.
                model_keepwarm.record_startup_probe(elapsed)
            logger.info("Warmup: %s LLM warm in %.2fs", label, elapsed)
        except Exception as exc:
            if interactive:
                # A model that was never pulled is not a fault -- it is the
                # normal state of a fresh install, and the fix is an install
                # button. Ollama reports it inside a connection error, so the
                # distinction has to be read out of the message.
                if _model_not_installed(exc):
                    status.set_state("chat_model", "missing", model or "")
                else:
                    status.set_state("chat_model", "failed", _friendly(exc, engine=True))
            logger.warning("Warmup: failed to warm %s LLM: %s", label, exc)

    try:
        from app.services.settings_service import get_effective_routing  # noqa: PLC0415

        fg = get_effective_routing(background=False)[0]
        bg = get_effective_routing(background=True)[0]
    except Exception:
        fg, bg = None, None

    from app.services.llm_routing import refusal  # noqa: PLC0415

    if not _unavailable_here("chat", "chat_model"):
        await _one(None, "interactive")
    if bg and bg != fg and refusal("background") is None:
        await _one(bg, "background")


_background: set[asyncio.Task] = set()


def warm_chat_model() -> None:
    """Load the chat model just installed, in the background.

    Without this the first load -- and the offload measurement -- waits for the
    user's first question or the next launch.
    """
    get_startup_status().set_state("chat_model", "loading", "")
    task = asyncio.get_running_loop().create_task(_warm_llm())
    _background.add(task)
    task.add_done_callback(_background.discard)


def _unavailable_here(role: str, phase: str) -> bool:
    """Mark *phase* unavailable when this host refuses the local model *role* uses.

    Not a failure: nothing will fix it by retrying, and offering an install or a
    problem report for it sent a user down both.
    """
    from app.host_support import local_inference_support  # noqa: PLC0415
    from app.services.llm_routing import refusal  # noqa: PLC0415

    if refusal(role) is None:
        return False
    get_startup_status().set_state(phase, "unavailable", local_inference_support().message or "")
    return True


async def _check_vision_model() -> None:
    """Report whether the vision model is installed, without loading it.

    Not warmed: 6GB into memory at every startup costs more than the first
    figure it would read. The tag list answers the only question here.
    """
    from app.services.components import component_status  # noqa: PLC0415
    from app.services.settings_service import get_vision_model  # noqa: PLC0415

    if _unavailable_here("vision", "vision_model"):
        return
    status = get_startup_status()
    try:
        installed = {c["id"]: c["installed"] for c in await component_status()}
    except Exception as exc:
        status.set_state("vision_model", "failed", _friendly(exc, engine=True))
        return

    if installed.get("vision_model"):
        status.set_state("vision_model", "ready", get_vision_model())
    else:
        status.set_state("vision_model", "missing", get_vision_model())


async def run_warmup(only: set[str] | None = None) -> None:
    """Fetch and load the local models. Safe to call again to retry failures."""
    status = get_startup_status()

    if _lock.locked():
        logger.info("Warmup already in progress; ignoring re-entry")
        return

    async with _lock:
        wanted = model_prefetch.specs()
        if only is not None:
            wanted = tuple(s for s in wanted if s.key in only)

        missing = [s for s in wanted if not s.on_request and not model_prefetch.is_cached(s)]
        reachable = True
        if missing:
            loop = asyncio.get_running_loop()
            reachable = await loop.run_in_executor(None, model_prefetch.hub_reachable)
            status.set_offline(not reachable)
            if not reachable:
                logger.warning("Model prefetch skipped: hub unreachable")

        async def provision(key: str, load) -> None:
            """Fetch this model if needed, then construct it.

            Per model rather than one batch: the embedder is 128MB and the
            entity model 1.1GB, so batching made the app wait on the larger
            download before it could construct the smaller one. Downloads
            overlap across these tasks; construction still serialises on the
            single-worker executor and MODEL_LOAD_LOCK.
            """
            spec = model_prefetch.spec_for(key)
            if spec is not None and not model_prefetch.is_cached(spec):
                if spec.on_request:
                    status.set_state(key, "missing", spec.repo_id)
                    return
                if not reachable:
                    # Constructing would only rediscover this, slowly, and
                    # replace the message that tells the user what to do.
                    status.set_state(
                        key,
                        "failed",
                        "No internet connection. Luminary needs to download this once.",
                    )
                    return
                status.set_state(key, "downloading", spec.repo_id)
                errors = await asyncio.get_running_loop().run_in_executor(
                    None, model_prefetch.prefetch, [spec], status
                )
                if key in errors:
                    status.set_state(key, "failed", _friendly(Exception(errors[key])))
                    return
            await load()

        tasks = []
        if only is None or "embedder" in only:
            tasks.append(provision("embedder", _load_embedder))
        if only is None or "ner" in only:
            tasks.append(provision("ner", _load_ner))
        if only is None or "reranker" in only:
            tasks.append(provision("reranker", _load_reranker))
        # The chat model lives in Ollama, not the HuggingFace cache.
        if only is None or "chat_model" in only:
            tasks.append(_warm_llm())
        if only is None or "vision_model" in only:
            tasks.append(_check_vision_model())

        await asyncio.gather(*tasks)


async def retry_failed() -> list[str]:
    """Re-run whatever failed. Returns the phase keys that were retried."""
    snapshot = get_startup_status().snapshot()
    failed = {p["key"] for p in snapshot["phases"] if p["state"] == "failed"}
    if not failed:
        return []
    await run_warmup(only=failed)
    return sorted(failed)
