import asyncio
import logging
import logging.config
import os
import shutil
import signal
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel, RootModel
from pythonjsonlogger.json import JsonFormatter
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db, get_engine, get_session_factory
from app.db_init import create_all_tables
from app.models import SettingsModel
from app.routers.admin import router as admin_router
from app.routers.annotations import router as annotations_router
from app.routers.blog import router as blog_router
from app.routers.chat_meta import router as chat_meta_router
from app.routers.chat_sessions import router as chat_sessions_router
from app.routers.clips import router as clips_router
from app.routers.code_executor import router as code_executor_router
from app.routers.collections import router as collections_router
from app.routers.documents import router as documents_router
from app.routers.engagement import router as engagement_router
from app.routers.evals import router as evals_router
from app.routers.explain import router as explain_router
from app.routers.feynman import router as feynman_router
from app.routers.flashcards import router as flashcards_router
from app.routers.goals import router as goals_router
from app.routers.graph import router as graph_router
from app.routers.home import router as home_router
from app.routers.images import router as images_router
from app.routers.mastery import router as mastery_router
from app.routers.monitoring import router as monitoring_router
from app.routers.notes import router as notes_router
from app.routers.pomodoro import router as pomodoro_router
from app.routers.qa import router as qa_router
from app.routers.reading import router as reading_router
from app.routers.references import router as references_router
from app.routers.search import router as search_router
from app.routers.sections import router as sections_router
from app.routers.settings import router as settings_router
from app.routers.study import router as study_router
from app.routers.summarize import router as summarize_router
from app.routers.tags import router as tags_router
from app.services.concept_linker import concept_link_handler
from app.services.diagram_extractor import diagram_extract_handler
from app.services.enrichment_worker import get_enrichment_worker
from app.services.image_enricher import image_analyze_handler
from app.services.image_extractor import image_extract_handler
from app.services.prereq_extractor import prereq_extract_handler
from app.services.reference_enricher import web_refs_handler
from app.services.settings_service import _cache as _llm_cache
from app.services.settings_service import load_llm_settings, read_labs_enabled_sync
from app.surface_manifest import enabled_routers
from app.telemetry import setup_tracing


def configure_logging(log_level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    if log_level != "DEBUG":
        handler.setFormatter(JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logger = logging.getLogger()
    logger.handlers = [handler]
    logger.setLevel(log_level)


logger = logging.getLogger(__name__)


def _read_app_version() -> str:
    try:
        import tomllib

        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with pyproject.open("rb") as fh:
            return tomllib.load(fh)["project"]["version"]
    except Exception:
        return "0.0.0"


_APP_VERSION = _read_app_version()


def _release_kuzu_lock(kuzu_path: Path) -> None:
    """Kill any other processes holding an open file handle on the Kuzu database file."""
    if not kuzu_path.exists():
        return
    try:
        result = subprocess.run(
            ["lsof", "-t", str(kuzu_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        pids = [int(p) for p in result.stdout.split() if p.strip().isdigit()]
        current_pid = os.getpid()
        for pid in pids:
            if pid == current_pid:
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                logger.warning(
                    "Released Kuzu lock by terminating stale process", extra={"pid": pid}
                )
            except ProcessLookupError:
                pass
    except Exception:
        logger.warning("Could not check/release Kuzu lock -- proceeding anyway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    # Release any stale Kuzu lock before initialising the graph service
    kuzu_path = Path(settings.DATA_DIR).expanduser() / "graph.kuzu"
    _release_kuzu_lock(kuzu_path)

    # Initial DB setup
    engine = get_engine()
    await create_all_tables(engine)

    # Telemetry setup
    if settings.PHOENIX_ENABLED:
        setup_tracing(phoenix_enabled=True, data_dir=settings.DATA_DIR)
        FastAPIInstrumentor.instrument_app(app)

    data_dir = Path(settings.DATA_DIR).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "corpus").mkdir(exist_ok=True)
    (data_dir / "images").mkdir(exist_ok=True)
    (data_dir / "notes").mkdir(exist_ok=True)
    (data_dir / "audio").mkdir(exist_ok=True)

    # Startup health check (Ollama) — only warn when private/hybrid mode needs it
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            if resp.status_code == 200:
                logger.info("Ollama reachable at %s", settings.OLLAMA_URL)
    except Exception:

        _mode = _llm_cache.get("llm_mode", "private")
        if _mode in ("private", "hybrid"):
            logger.warning(
                "Ollama unreachable at startup (mode=%s) — local LLM features will be degraded. "
                "Ensure Ollama is running at: %s",
                _mode,
                settings.OLLAMA_URL,
            )
        else:
            logger.debug("Ollama not reachable at startup (mode=%s, not needed)", _mode)

    # ffmpeg check — required for video (MP4) ingestion.
    _ffmpeg_path = shutil.which("ffmpeg")
    if _ffmpeg_path is None:
        logger.warning(
            "ffmpeg not found at startup — video (MP4) ingestion will be unavailable. "
            "Install with: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)"
        )
    else:
        logger.info("ffmpeg found at startup", extra={"path": _ffmpeg_path})

    # Register enrichment handlers and start the background worker
    # Must be done before yielding so jobs enqueued during first request are dispatched.

    _worker = get_enrichment_worker()
    _worker.register("image_extract", image_extract_handler)
    _worker.register("image_analyze", image_analyze_handler)
    _worker.register("diagram_extract", diagram_extract_handler)
    _worker.register("web_refs", web_refs_handler)
    _worker.register("prerequisites", prereq_extract_handler)
    _worker.register("concept_link", concept_link_handler)
    await _worker.start()

    # Load persisted LLM settings into cache so cloud mode is active from first request,
    # not only after the frontend hits GET /settings/llm.
    try:

        async with get_session_factory()() as _settings_db:
            await load_llm_settings(_settings_db)
        logger.info("LLM settings loaded from DB")
    except Exception:
        logger.warning("Failed to load LLM settings at startup; using defaults", exc_info=True)

    # Start pre-loading/warming up models in the background (skipped in test runs)
    import sys

    if "pytest" not in sys.modules:

        async def warmup_models():
            loop = asyncio.get_running_loop()

            async def load_embedder():
                try:
                    logger.info("Warmup: pre-loading Embedding model in the background...")
                    from app.services.embedder import get_embedding_service
                    await loop.run_in_executor(None, get_embedding_service()._load_model)
                    logger.info("Warmup: Embedding model pre-loaded.")
                except Exception as exc:
                    logger.warning("Warmup: failed to pre-load embedding model: %s", exc)

            async def load_ner():
                try:
                    logger.info("Warmup: pre-loading GLiNER model in the background...")
                    from app.services.ner import get_entity_extractor
                    await loop.run_in_executor(None, get_entity_extractor()._load_model)
                    logger.info("Warmup: GLiNER model pre-loaded.")
                except Exception as exc:
                    logger.warning("Warmup: failed to pre-load GLiNER model: %s", exc)

            async def load_llm():
                # Fire a tiny generation so the first user query doesn't pay the
                # cold-start cost: for Ollama this loads the model into memory,
                # for cloud it warms the connection / validates routing. Fails
                # soft — a missing key or offline model must not block startup.
                import time as _time

                from app.services.llm import get_llm_service

                async def _warm_one(model: str | None, label: str) -> None:
                    try:
                        t0 = _time.perf_counter()
                        logger.info("Warmup: warming %s LLM...", label)
                        await get_llm_service().generate(
                            "ping", model=model, timeout=60.0
                        )
                        logger.info(
                            "Warmup: %s LLM warm in %.2fs", label, _time.perf_counter() - t0
                        )
                    except Exception as exc:
                        logger.warning("Warmup: failed to warm %s LLM: %s", label, exc)

                # Resolve the interactive (foreground) and background models; warm
                # each distinct one. In hybrid mode these differ (cloud vs Ollama).
                try:
                    from app.services.settings_service import get_effective_routing
                    fg = get_effective_routing(background=False)[0]
                    bg = get_effective_routing(background=True)[0]
                except Exception:
                    fg, bg = None, None
                await _warm_one(None, "interactive")
                if bg and bg != fg:
                    await _warm_one(bg, "background")

            await asyncio.gather(load_embedder(), load_ner(), load_llm())

        asyncio.create_task(warmup_models())

    logger.info("Luminary backend started", extra={"data_dir": str(data_dir)})
    yield
    logger.info("Luminary backend shutting down")

    await get_enrichment_worker().stop()


app = FastAPI(title="Luminary", lifespan=lifespan)

_mode = get_settings().LUMINARY_MODE
# prod is single-origin (SPA + API on one port), so CORS is unnecessary; dev
# serves the frontend from Vite on a different port and needs it.
if _mode == "dev":
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://localhost:\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# In prod the whole API lives under /api so SPA client routes (/notes, /study,
# /collections/:id, ...) never collide with router paths. dev/test keep routers
# at root, so no test paths change.
_API_PREFIX = "/api" if _mode == "prod" else ""


ROUTER_REGISTRY = {
    "admin": admin_router,
    "annotations": annotations_router,
    "blog": blog_router,
    "clips": clips_router,
    "collections": collections_router,
    "chat_meta": chat_meta_router,
    "chat_sessions": chat_sessions_router,
    "documents": documents_router,
    "engagement": engagement_router,
    "evals": evals_router,
    "explain": explain_router,
    "goals": goals_router,
    "feynman": feynman_router,
    "flashcards": flashcards_router,
    "graph": graph_router,
    "home": home_router,
    "images": images_router,
    "monitoring": monitoring_router,
    "notes": notes_router,
    "pomodoro": pomodoro_router,
    "qa": qa_router,
    "reading": reading_router,
    "references": references_router,
    "search": search_router,
    "sections": sections_router,
    "settings": settings_router,
    "mastery": mastery_router,
    "study": study_router,
    "code_executor": code_executor_router,
    "summarize": summarize_router,
    "tags": tags_router,
}

# settings is always registered: the Settings -> Labs panel needs it to toggle tiers.
_tier = get_settings().LUMINARY_SURFACE_TIER
_labs_enabled = read_labs_enabled_sync() if _tier != "dev" else set()
_enabled = enabled_routers(_tier, _labs_enabled) | {"settings"}
for _name, _router in ROUTER_REGISTRY.items():
    if _name in _enabled:
        app.include_router(_router, prefix=_API_PREFIX)

# Misc app-level endpoints that live alongside the routers (root in dev, /api in prod).
misc_router = APIRouter()


@app.get("/health")
async def health():
    return {"status": "ok", "version": _APP_VERSION}


@misc_router.get("/settings")
async def read_settings(settings: Settings = Depends(get_settings)):
    def mask(value: str) -> str:
        if value:
            return value[:4] + "***"
        return ""

    return {
        "DATA_DIR": settings.DATA_DIR,
        "OLLAMA_URL": settings.OLLAMA_URL,
        "LOG_LEVEL": settings.LOG_LEVEL,
        "LITELLM_DEFAULT_MODEL": settings.LITELLM_DEFAULT_MODEL,
        "PHOENIX_ENABLED": settings.PHOENIX_ENABLED,
        "OPENAI_API_KEY": mask(settings.OPENAI_API_KEY),
        "ANTHROPIC_API_KEY": mask(settings.ANTHROPIC_API_KEY),
        "GOOGLE_API_KEY": mask(settings.GOOGLE_API_KEY),
        "LANGFUSE_PUBLIC_KEY": mask(settings.LANGFUSE_PUBLIC_KEY),
        "LANGFUSE_SECRET_KEY": mask(settings.LANGFUSE_SECRET_KEY),
    }


class SettingsUpdate(RootModel[dict[str, str]]):
    pass


@misc_router.patch("/settings")
async def patch_settings(
    request: SettingsUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    # TODO: migrate to OS keychain — see tech-debt-tracker.md
    updates = request.root
    for key, value in updates.items():
        setting = SettingsModel(key=key, value=value)
        await session.merge(setting)
    await session.commit()
    return {"updated": list(updates.keys())}


class OllamaPullRequest(BaseModel):
    model: str


@misc_router.post("/settings/ollama/pull")
async def pull_ollama_model(request: OllamaPullRequest) -> StreamingResponse:
    model = request.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="model is required")

    async def _stream():
        proc = await asyncio.create_subprocess_exec(
            "ollama",
            "pull",
            model,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        async for line in proc.stdout:
            yield f"data: {line.decode().rstrip()}\n\n"
        await proc.wait()
        yield "data: done\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@misc_router.get("/settings/storage")
async def read_storage(settings: Settings = Depends(get_settings)) -> dict:
    data_dir = Path(settings.DATA_DIR).expanduser()

    def dir_size_mb(path: Path) -> float:
        if not path.exists():
            return 0.0
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return round(total / (1024 * 1024), 2)

    return {
        "corpus_mb": dir_size_mb(data_dir / "corpus"),
        "images_mb": dir_size_mb(data_dir / "images"),
        "notes_mb": dir_size_mb(data_dir / "notes"),
        "audio_mb": dir_size_mb(data_dir / "audio"),
        "db_mb": dir_size_mb(data_dir / "luminary.db")
        if (data_dir / "luminary.db").exists()
        else 0.0,
    }


app.include_router(misc_router, prefix=_API_PREFIX)


def resolve_spa_asset(dist: Path, full_path: str) -> Path | None:
    """Resolve a request path to a real file inside ``dist``, or None.

    Returns None for empty paths and for any path that escapes ``dist`` (e.g.
    ``../`` traversal), so callers fall back to index.html. Containment is the
    load-bearing check: ``serve_spa`` is the only unauthenticated catch-all in
    prod, so a path that resolves outside ``dist`` must never be served.
    """
    if not full_path:
        return None
    candidate = (dist / full_path).resolve()
    if candidate.is_file() and candidate.is_relative_to(dist.resolve()):
        return candidate
    return None


# In prod, serve the built SPA. The API is under /api, so everything else falls
# back to index.html for client-side routing (real files are served directly).
if _mode == "prod":
    _DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        asset = resolve_spa_asset(_DIST, full_path)
        if asset is not None:
            return FileResponse(asset)
        return FileResponse(_DIST / "index.html")
