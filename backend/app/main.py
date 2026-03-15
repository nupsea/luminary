import asyncio
import logging
import logging.config
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel
from pythonjsonlogger.json import JsonFormatter
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db, get_engine
from app.db_init import create_all_tables
from app.models import SettingsModel
from app.routers.annotations import router as annotations_router
from app.routers.chat_meta import router as chat_meta_router
from app.routers.documents import router as documents_router
from app.routers.evals import router as evals_router
from app.routers.explain import router as explain_router
from app.routers.flashcards import router as flashcards_router
from app.routers.goals import router as goals_router
from app.routers.graph import router as graph_router
from app.routers.images import router as images_router
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
from app.services.graph import get_graph_service
from app.telemetry import setup_tracing


def configure_logging(log_level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    if log_level != "DEBUG":
        handler.setFormatter(JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.basicConfig(level=log_level, handlers=[handler])


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    data_dir = Path(settings.DATA_DIR).expanduser()
    for subdir in ("raw", "models", "vectors", "images"):
        (data_dir / subdir).mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    await create_all_tables(engine)
    setup_tracing(settings.PHOENIX_ENABLED, data_dir=str(data_dir))
    FastAPIInstrumentor.instrument_app(app)
    # SQLAlchemyInstrumentor is intentionally omitted — it instruments all
    # SQLAlchemy engines globally, including Phoenix's own phoenix.db, creating
    # a trace-feedback loop (Phoenix traces → phoenix.db write → new trace → …).
    get_graph_service()  # initialise KuzuService and create schema on startup

    # Start enrichment queue worker and register job handlers
    from app.services.diagram_extractor import diagram_extract_handler  # noqa: PLC0415
    from app.services.enrichment_worker import get_enrichment_worker  # noqa: PLC0415
    from app.services.image_enricher import image_analyze_handler  # noqa: PLC0415
    from app.services.image_extractor import image_extract_handler  # noqa: PLC0415
    from app.services.reference_enricher import web_refs_handler  # noqa: PLC0415

    worker = get_enrichment_worker()
    worker.register("image_extract", image_extract_handler)
    worker.register("image_analyze", image_analyze_handler)
    worker.register("diagram_extract", diagram_extract_handler)
    worker.register("web_refs", web_refs_handler)
    await worker.start()

    # Ollama startup health-check — warn early if the local LLM is unreachable.
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            if resp.status_code == 200:
                logger.info("Ollama reachable at startup", extra={"url": settings.OLLAMA_URL})
            else:
                logger.warning(
                    "Ollama returned non-200 at startup; LLM features may be degraded. "
                    "URL: %s  status: %s",
                    settings.OLLAMA_URL,
                    resp.status_code,
                )
    except Exception:
        logger.warning(
            "Ollama unreachable at startup — LLM features will be degraded. "
            "Ensure Ollama is running at: %s",
            settings.OLLAMA_URL,
        )

    # ffmpeg check — required for video (MP4) ingestion.
    _ffmpeg_path = shutil.which("ffmpeg")
    if _ffmpeg_path is None:
        logger.warning(
            "ffmpeg not found at startup — video (MP4) ingestion will be unavailable. "
            "Install with: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)"
        )
    else:
        logger.info("ffmpeg found at startup", extra={"path": _ffmpeg_path})

    logger.info("Luminary backend started", extra={"data_dir": str(data_dir)})
    yield
    logger.info("Luminary backend shutting down")
    from app.services.enrichment_worker import get_enrichment_worker as _get_worker  # noqa: PLC0415

    await _get_worker().stop()


app = FastAPI(title="Luminary", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:1420"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(annotations_router)
app.include_router(chat_meta_router)
app.include_router(documents_router)
app.include_router(evals_router)
app.include_router(explain_router)
app.include_router(goals_router)
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
app.include_router(study_router)
app.include_router(summarize_router)


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


@app.patch("/settings")
async def patch_settings(
    updates: dict[str, str],
    session: AsyncSession = Depends(get_db),
) -> dict:
    # TODO: migrate to OS keychain — see tech-debt-tracker.md
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
        "data_dir": str(data_dir),
        "raw_mb": dir_size_mb(data_dir / "raw"),
        "vectors_mb": dir_size_mb(data_dir / "vectors"),
        "models_mb": dir_size_mb(data_dir / "models"),
    }
