import asyncio
import logging
import logging.config
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
from app.routers.documents import router as documents_router
from app.routers.explain import router as explain_router
from app.routers.flashcards import router as flashcards_router
from app.routers.graph import router as graph_router
from app.routers.monitoring import router as monitoring_router
from app.routers.notes import router as notes_router
from app.routers.qa import router as qa_router
from app.routers.search import router as search_router
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
    for subdir in ("raw", "models", "vectors"):
        (data_dir / subdir).mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    await create_all_tables(engine)
    setup_tracing(settings.PHOENIX_ENABLED, data_dir=str(data_dir))
    FastAPIInstrumentor.instrument_app(app)
    # SQLAlchemyInstrumentor is intentionally omitted — it instruments all
    # SQLAlchemy engines globally, including Phoenix's own phoenix.db, creating
    # a trace-feedback loop (Phoenix traces → phoenix.db write → new trace → …).
    get_graph_service()  # initialise KuzuService and create schema on startup

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

    logger.info("Luminary backend started", extra={"data_dir": str(data_dir)})
    yield
    logger.info("Luminary backend shutting down")


app = FastAPI(title="Luminary", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:1420"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(documents_router)
app.include_router(explain_router)
app.include_router(flashcards_router)
app.include_router(graph_router)
app.include_router(monitoring_router)
app.include_router(notes_router)
app.include_router(qa_router)
app.include_router(search_router)
app.include_router(study_router)
app.include_router(summarize_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/settings/llm")
async def read_llm_settings(settings: Settings = Depends(get_settings)):
    available_local_models: list[str] = []
    processing_mode = "unavailable"

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                # Prefix with "ollama/" so LiteLLM can route the call correctly.
                available_local_models = [
                    f"ollama/{m['name']}" for m in data.get("models", [])
                ]
                processing_mode = "local"
    except Exception:
        pass

    cloud_providers = [
        {"name": "openai", "available": bool(settings.OPENAI_API_KEY)},
        {"name": "anthropic", "available": bool(settings.ANTHROPIC_API_KEY)},
        {"name": "gemini", "available": bool(settings.GOOGLE_API_KEY)},
    ]

    if processing_mode == "unavailable" and any(p["available"] for p in cloud_providers):
        processing_mode = "cloud"

    return {
        "processing_mode": processing_mode,
        "active_model": settings.LITELLM_DEFAULT_MODEL,
        "available_local_models": available_local_models,
        "cloud_providers": cloud_providers,
    }


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
