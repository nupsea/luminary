import logging
import logging.config
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pythonjsonlogger.json import JsonFormatter

from app.config import Settings, get_settings
from app.database import get_engine
from app.db_init import create_all_tables
from app.routers.documents import router as documents_router


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
    await create_all_tables(get_engine())
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
                available_local_models = [m["name"] for m in data.get("models", [])]
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
