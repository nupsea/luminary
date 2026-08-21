import asyncio
import logging
import logging.config
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel, RootModel
from pythonjsonlogger.json import JsonFormatter
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings, get_settings
from app.database import get_db, get_engine, get_session_factory
from app.db_init import init_database
from app.exceptions import LuminaryError
from app.models import SettingsModel
from app.parent_watch import watch_parent
from app.paths import app_version, spa_dist
from app.routers.admin import router as admin_router
from app.routers.annotations import router as annotations_router
from app.routers.blog import router as blog_router
from app.routers.chat_meta import router as chat_meta_router
from app.routers.chat_sessions import router as chat_sessions_router
from app.routers.clips import router as clips_router
from app.routers.collections import router as collections_router
from app.routers.concepts import router as concepts_router
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
from app.routers.model_lab import router as model_lab_router
from app.routers.monitoring import router as monitoring_router
from app.routers.notes import router as notes_router
from app.routers.pomodoro import router as pomodoro_router
from app.routers.progress import router as progress_router
from app.routers.qa import router as qa_router
from app.routers.reading import router as reading_router
from app.routers.references import router as references_router
from app.routers.search import router as search_router
from app.routers.sections import router as sections_router
from app.routers.settings import router as settings_router
from app.routers.setup import router as setup_router
from app.routers.study import router as study_router
from app.routers.summarize import router as summarize_router
from app.routers.tags import router as tags_router
from app.services.components import activate_extras, install_ollama_model, resolve_tool
from app.services.concept_linker import concept_link_handler
from app.services.diagram_extractor import diagram_extract_handler
from app.services.enrichment_worker import get_enrichment_worker
from app.services.executors import shutdown_model_executor
from app.services.image_enricher import image_analyze_handler
from app.services.image_extractor import image_extract_handler
from app.services.ingestion_jobs import get_ingestion_jobs
from app.services.prereq_extractor import prereq_extract_handler
from app.services.reference_enricher import web_refs_handler
from app.services.settings_service import _cache as _llm_cache
from app.services.settings_service import load_llm_settings
from app.services.startup_status import get_startup_status
from app.services.warmup import run_warmup
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


_APP_VERSION = app_version()

# Warmup and the description backfill were fire-and-forget, so nothing cancelled
# them at shutdown and nothing held a reference against garbage collection.
_background_tasks: set[asyncio.Task] = set()
_SHUTDOWN_GRACE_S = 5.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    # Before the migration below: if the desktop shell dies while we are still
    # starting, nothing else would ever stop us, and the Kuzu lock we go on to
    # take would block the user's next launch.
    watch_parent()

    # Initial DB setup
    status = get_startup_status()
    status.set_state("db", "loading", "SQLite schema + LanceDB and Kuzu stores")
    engine = get_engine()
    try:
        await init_database(engine)
    except Exception as exc:
        status.set_state("db", "failed", str(exc))
        raise
    status.set_state("db", "ready")

    # Say it out loud at boot, not only at GET /settings/models. An oversized
    # configuration's first symptom was a crash during ingestion, which is the
    # least useful moment to learn that the models do not fit.
    try:
        from app.services.model_router import warn_if_configuration_exceeds_host

        warn_if_configuration_exceeds_host()
    except Exception:  # noqa: BLE001 -- an advisory check may never block startup
        # warning, not debug: this swallowed a TypeError in the check itself for
        # as long as the check existed, so the advisory never ran and nothing said so.
        logger.warning("model residency check failed", exc_info=True)
    # NOTE: concept regeneration is a manual offline step (with the server stopped
    # so it can hold the Kuzu lock and not starve the event loop):
    #   make concepts
    # See docs/concepts.md.

    # Telemetry setup
    if settings.PHOENIX_ENABLED:
        setup_tracing(phoenix_enabled=True, data_dir=settings.DATA_DIR)
        FastAPIInstrumentor.instrument_app(app)

    data_dir = Path(settings.DATA_DIR).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    # The library holds the user's documents, notes and (when no keyring is
    # available) API keys. Default mkdir/umask leaves it 0o755 -- readable by
    # every other local account and every unsandboxed app the user runs.
    _restrict_permissions(data_dir)
    (data_dir / "corpus").mkdir(exist_ok=True)
    (data_dir / "images").mkdir(exist_ok=True)
    (data_dir / "notes").mkdir(exist_ok=True)
    (data_dir / "audio").mkdir(exist_ok=True)

    # Components the user installed after the app itself. Must happen before
    # anything tries to import them.
    if activate_extras():
        logger.info("Activated user-installed extras", extra={"path": str(data_dir / "extras")})

    # Startup health check (Ollama) — only warn when private/hybrid mode needs it
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            if resp.status_code == 200:
                logger.info("Ollama reachable at %s", settings.OLLAMA_URL)
                status.set_state("ollama_server", "ready", settings.OLLAMA_URL)
    except Exception:
        status.set_state(
            "ollama_server", "failed", f"No local model server at {settings.OLLAMA_URL}"
        )

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
    _ffmpeg_path = resolve_tool("ffmpeg")
    if _ffmpeg_path is None:
        logger.warning(
            "ffmpeg not found at startup — video (MP4) ingestion will be unavailable. "
            "Add audio and video support from Settings."
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

    # An ingestion that was running when the process died cannot resume: its task
    # is gone and nothing owns the document any more. It used to keep its last
    # stage for ever, so the UI showed a progress card that would never finish --
    # seen twice on 2026-08-17, when a code reload under `uvicorn --reload` killed
    # a 52,331-chunk embed at 70%. An interrupted ingest is now marked failed at
    # startup, which is a state the user can act on (I-10).
    try:
        from sqlalchemy import update  # noqa: PLC0415

        from app.models import DocumentModel  # noqa: PLC0415

        _terminal_stages = ("complete", "error")
        async with get_session_factory()() as _session:
            result = await _session.execute(
                update(DocumentModel)
                .where(DocumentModel.stage.notin_(_terminal_stages))
                .values(
                    stage="error",
                    error_message=(
                        "Ingestion was interrupted before it finished. "
                        "Delete this document and upload it again."
                    ),
                )
            )
            await _session.commit()
        if result.rowcount:
            logger.warning(
                "marked %d interrupted ingestion(s) as failed at startup", result.rowcount
            )
    except Exception:
        logger.warning("could not reconcile interrupted ingestions", exc_info=True)

    # Model-lab comparisons take hours; without this they exist only for the
    # life of the process, and `uvicorn --reload` restarts on every edit.
    try:
        from app.services.model_lab import load_history  # noqa: PLC0415

        load_history()
    except Exception:
        logger.warning("Failed to load model-lab history", exc_info=True)

    # Start pre-loading/warming up models in the background (skipped in test runs)
    import sys

    if "pytest" not in sys.modules:

        _background_tasks.add(asyncio.create_task(run_warmup()))

        # One-time-ish backfill: summarise notes created before card descriptions
        # existed. Runs after a short delay so it doesn't compete with model
        # warmup; no-ops once every note has a description.
        async def backfill_descriptions():
            try:
                await asyncio.sleep(20)
                from app.services.notes_service import backfill_missing_descriptions
                await backfill_missing_descriptions()
            except Exception as exc:
                logger.warning("Description backfill failed (non-fatal): %s", exc)

        _background_tasks.add(asyncio.create_task(backfill_descriptions()))

    logger.info("Luminary backend started", extra={"data_dir": str(data_dir)})
    yield
    logger.info("Luminary backend shutting down")

    # Every step here is bounded. A desktop app that takes minutes to quit reads
    # as a hang, and a supervisor that gives up and SIGKILLs can leave the Kuzu
    # lock held against the next launch.
    await get_enrichment_worker().stop()
    await get_ingestion_jobs().cancel_all()

    for task in list(_background_tasks):
        task.cancel()
    if _background_tasks:
        await asyncio.wait(_background_tasks, timeout=_SHUTDOWN_GRACE_S)
        _background_tasks.clear()

    shutdown_model_executor()


def _resolve_chat_model() -> str:
    """What a chat would actually be served by, resolved not configured."""
    from app.services.model_router import resolve  # noqa: PLC0415

    return resolve("chat").model


def _restrict_permissions(data_dir: Path) -> None:
    """Tighten the library to owner-only. Best-effort: a mounted volume may not
    permit chmod, and that must not stop the app from starting."""
    for path, mode in (
        (data_dir, 0o700),
        (data_dir / "luminary.db", 0o600),
        (data_dir / "luminary.db-wal", 0o600),
        (data_dir / "luminary.db-shm", 0o600),
    ):
        try:
            if path.exists():
                path.chmod(mode)
        except OSError as exc:
            logger.warning("Could not restrict permissions on %s: %s", path, exc)


app = FastAPI(title="Luminary", lifespan=lifespan)


@app.exception_handler(LuminaryError)
async def _domain_error_handler(_request: Request, exc: LuminaryError) -> JSONResponse:
    body: dict[str, object] = {"detail": exc.detail}
    body.update(exc.extra)
    return JSONResponse(status_code=exc.status_code, content=body)


_mode = get_settings().LUMINARY_MODE

# Load-bearing against DNS rebinding. The server binds loopback and has no
# authentication, so it trusts the network boundary entirely -- but a hostile
# page can rebind its own domain to 127.0.0.1 and become same-origin, which
# turns every endpoint into a readable, writable, same-origin resource. Pinning
# Host to loopback names rejects those requests before routing.
# Starlette strips the port before matching, so bare hostnames are correct here
# (a "host:*" pattern would fail its wildcard assertion at import). Skipped under
# pytest, where the ASGI transport invents its own Host values.
if "pytest" not in sys.modules:
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "::1"]
    )
# public is single-origin (SPA + API on one port), so CORS is unnecessary; full
# serves the frontend from Vite on a different port and needs it.
if _mode == "full":
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://localhost:\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# In public mode the whole API lives under /api so SPA client routes (/notes,
# /study, /collections/:id, ...) never collide with router paths. full/test keep
# routers at root, so no test paths change.
_API_PREFIX = "/api" if _mode == "public" else ""


ROUTER_REGISTRY = {
    "admin": admin_router,
    "annotations": annotations_router,
    "blog": blog_router,
    "clips": clips_router,
    "collections": collections_router,
    "concepts": concepts_router,
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
    "model_lab": model_lab_router,
    "monitoring": monitoring_router,
    "notes": notes_router,
    "pomodoro": pomodoro_router,
    "progress": progress_router,
    "qa": qa_router,
    "reading": reading_router,
    "references": references_router,
    "search": search_router,
    "sections": sections_router,
    "settings": settings_router,
    "setup": setup_router,
    "mastery": mastery_router,
    "study": study_router,
    "summarize": summarize_router,
    "tags": tags_router,
}

# settings and setup are always registered: the Settings drawer needs one, and
# the other is what a user with an incomplete install has to reach.
_enabled = enabled_routers(_mode) | {"settings", "setup"}
for _name, _router in ROUTER_REGISTRY.items():
    if _name in _enabled:
        app.include_router(_router, prefix=_API_PREFIX)

# Misc app-level endpoints that live alongside the routers (root in dev, /api in prod).
misc_router = APIRouter()

# Probes are registered at BOTH the root and the API prefix. Process supervisors,
# container health checks and the desktop shell all probe before any SPA exists
# and know nothing about /api; the SPA calls them through its own /api base. When
# these lived only at the root, the About dialog's version request for
# /api/health hit serve_spa's 404-for-api/ guard in every shipped build.
probe_router = APIRouter()


@probe_router.get("/health")
async def health():
    return {"status": "ok", "version": _APP_VERSION}


@probe_router.get("/healthz")
async def healthz():
    """Lightweight liveness probe for containers and monitors (no DB)."""
    from datetime import UTC, datetime

    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}


@probe_router.get("/setup/status")
async def setup_status():
    """What startup has actually finished, as opposed to /health's 200."""
    snapshot = get_startup_status().snapshot()
    snapshot["version"] = _APP_VERSION
    return snapshot


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
        # The model that would actually serve a chat, which is not always the
        # configured default: Settings can point elsewhere.
        "chat_model": _resolve_chat_model(),
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
        # Ollama's HTTP API, not `ollama pull`. Spawning the binary required it
        # on PATH, which a GUI-launched process does not have, and it yielded
        # text lines instead of byte counts.
        async for event in install_ollama_model(model):
            if event["state"] == "failed":
                yield f"data: error: {event['detail']}\n\n"
                return
            if detail := event.get("detail"):
                yield f"data: {detail}\n\n"
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
app.include_router(probe_router, prefix=_API_PREFIX)
if _API_PREFIX:
    app.include_router(probe_router, include_in_schema=False)


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


# In public mode, serve the built SPA. The API is under /api, so everything else
# falls back to index.html for client-side routing (real files are served directly).
if _mode == "public":
    _DIST = spa_dist()

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        asset = resolve_spa_asset(_DIST, full_path)
        if asset is not None:
            return FileResponse(asset)
        index = _DIST / "index.html"
        if not index.is_file():
            # The SPA isn't built (or is mid-rebuild). Return a clean 503 rather
            # than letting FileResponse raise a 500 stack trace at the user.
            raise HTTPException(
                status_code=503,
                detail="Frontend not built. Run `make build` (dist/ is missing or rebuilding).",
            )
        return FileResponse(index)
