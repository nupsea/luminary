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
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
from app.routers.chat_meta import router as chat_meta_router
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
from app.routers.images import router as images_router
from app.routers.mastery import router as mastery_router
from app.routers.monitoring import router as monitoring_router
from app.routers.notes import router as notes_router
from app.routers.qa import router as qa_router
from app.routers.reading import router as reading_router
from app.routers.references import router as references_router
from app.routers.search import router as search_router
from app.routers.sections import router as sections_router
from app.routers.settings import router as settings_router
from app.routers.study import router as study_router
from app.routers.summarize import router as summarize_router
from app.routers.tags import router as tags_router
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
        from app.services.settings_service import _cache as _llm_cache  # noqa: PLC0415

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

    # Register enrichment handlers and start the background worker (S141)
    # Must be done before yielding so jobs enqueued during first request are dispatched.
    from app.services.concept_linker import concept_link_handler  # noqa: PLC0415
    from app.services.diagram_extractor import diagram_extract_handler  # noqa: PLC0415
    from app.services.enrichment_worker import get_enrichment_worker  # noqa: PLC0415
    from app.services.image_enricher import image_analyze_handler  # noqa: PLC0415
    from app.services.image_extractor import image_extract_handler  # noqa: PLC0415
    from app.services.prereq_extractor import prereq_extract_handler  # noqa: PLC0415
    from app.services.reference_enricher import web_refs_handler  # noqa: PLC0415

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
        from app.services.settings_service import load_llm_settings  # noqa: PLC0415

        async with get_session_factory()() as _settings_db:
            await load_llm_settings(_settings_db)
        logger.info("LLM settings loaded from DB")
    except Exception:
        logger.warning("Failed to load LLM settings at startup; using defaults", exc_info=True)

    logger.info("Luminary backend started", extra={"data_dir": str(data_dir)})
    yield
    logger.info("Luminary backend shutting down")
    from app.services.enrichment_worker import get_enrichment_worker as _get_worker  # noqa: PLC0415

    await _get_worker().stop()


app = FastAPI(title="Luminary", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(admin_router)
app.include_router(annotations_router)
app.include_router(clips_router)
app.include_router(collections_router)
app.include_router(chat_meta_router)
app.include_router(documents_router)
app.include_router(engagement_router)
app.include_router(evals_router)
app.include_router(explain_router)
app.include_router(goals_router)
app.include_router(feynman_router)
app.include_router(flashcards_router)
app.include_router(graph_router)
app.include_router(images_router)
app.include_router(monitoring_router)
app.include_router(notes_router)
app.include_router(qa_router)
app.include_router(reading_router)
app.include_router(references_router)
app.include_router(search_router)
app.include_router(sections_router)
app.include_router(settings_router)
app.include_router(mastery_router)
app.include_router(study_router)
app.include_router(code_executor_router)
app.include_router(summarize_router)
app.include_router(tags_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/settings")
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


@app.patch("/settings")
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


@app.post("/settings/ollama/pull")
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


@app.get("/settings/storage")
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
