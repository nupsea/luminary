import functools
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATA_DIR: str = ".luminary"
    LUMINARY_SURFACE_TIER: Literal["public", "labs", "dev"] = "dev"
    # prod: serve the built SPA and mount the API under /api on one port (no CORS).
    # dev: routers at root, CORS open, frontend served separately by Vite.
    LUMINARY_MODE: Literal["dev", "prod"] = "dev"
    OLLAMA_URL: str = "http://localhost:11434"
    LOG_LEVEL: str = "INFO"
    LITELLM_DEFAULT_MODEL: str = "ollama/gemma4"
    # Model for high-quality generation (flashcards, etc).
    # Falls back to DEFAULT_MODEL when empty.
    LITELLM_GENERATION_MODEL: str = ""
    PHOENIX_ENABLED: bool = True
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    WHISPER_MODEL_SIZE: str = "base"
    VISION_MODEL: str = "ollama/llava:7b"
    GLINER_ENABLED: bool = True  # Set to false on memory-constrained machines (avoids OOM)
    # 2D.2: seed document auto-tags with entities from the graph extraction.
    # On by default -- no extra LLM calls; uses entities already populated by
    # entity_extract_node. Requires GLINER_ENABLED at ingestion time for old docs
    # to have entities; new ingestions get entities automatically.
    AUTO_TAG_USE_ENTITIES: bool = True
    # Per-doc mention threshold for entity-as-tag selection. Higher = fewer,
    # more central tags. Scales naturally with document length: long technical
    # books yield many tags, short articles a handful. Default 3 -- combined
    # with the CONCEPT-only entity query and the stoplist, this keeps the
    # generic ambient-noun tail out of the rail.
    AUTO_TAG_ENTITY_MIN_MENTIONS: int = 3
    # Auto-tag minimum slug length. Two-char concept tags like 'ai' are useful
    # but anything shorter is almost always an extraction artifact.
    AUTO_TAG_MIN_SLUG_LENGTH: int = 2
    WEB_SEARCH_PROVIDER: str = "none"  # "none" | "brave" | "tavily" | "duckduckgo"
    BRAVE_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    ADMIN_KEY: str = ""
    PHOENIX_GRPC_PORT: int = 4317

    model_config = {"env_file": (".env", "/app/.luminary/.env"), "env_file_encoding": "utf-8"}


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
