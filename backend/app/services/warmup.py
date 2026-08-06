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

from app.config import get_settings
from app.services import model_prefetch
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


def _friendly(exc: Exception) -> str:
    """A sentence for a person, not a traceback.

    Raw exception text reached the setup screen and read as a crash;
    the detail is still logged in full.
    """
    text = str(exc)
    lowered = text.lower()
    if "connection" in lowered or "connect" in lowered:
        return "Could not reach the local model server."
    if "timeout" in lowered or "timed out" in lowered:
        return "Timed out while starting."
    return text.split("\n", 1)[0][:160]


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
            await get_llm_service().generate("ping", model=model, timeout=60.0)
            if interactive:
                status.set_state("chat_model", "ready", model or "")
            logger.info("Warmup: %s LLM warm in %.2fs", label, time.perf_counter() - t0)
        except Exception as exc:
            if interactive:
                # A model that was never pulled is not a fault -- it is the
                # normal state of a fresh install, and the fix is an install
                # button. Ollama reports it inside a connection error, so the
                # distinction has to be read out of the message.
                if _model_not_installed(exc):
                    status.set_state("chat_model", "missing", model or "")
                else:
                    status.set_state("chat_model", "failed", _friendly(exc))
            logger.warning("Warmup: failed to warm %s LLM: %s", label, exc)

    try:
        from app.services.settings_service import get_effective_routing  # noqa: PLC0415

        fg = get_effective_routing(background=False)[0]
        bg = get_effective_routing(background=True)[0]
    except Exception:
        fg, bg = None, None

    await _one(None, "interactive")
    if bg and bg != fg:
        await _one(bg, "background")


async def _check_vision_model() -> None:
    """Report whether the vision model is installed, without loading it.

    Not warmed: 6GB into memory at every startup costs more than the first
    figure it would read. The tag list answers the only question here.
    """
    from app.services.components import component_status  # noqa: PLC0415
    from app.services.settings_service import get_vision_model  # noqa: PLC0415

    status = get_startup_status()
    try:
        installed = {c["id"]: c["installed"] for c in await component_status()}
    except Exception as exc:
        status.set_state("vision_model", "failed", _friendly(exc))
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

        missing = [s for s in wanted if not model_prefetch.is_cached(s)]
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
