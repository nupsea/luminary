import functools
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATA_DIR: str = ".luminary"
    LUMINARY_SURFACE_TIER: Literal["public", "labs", "dev"] = "dev"
    # prod: serve the built SPA and mount the API under /api on one port (no CORS).
    # dev: routers at root, CORS open, frontend served separately by Vite.
    LUMINARY_MODE: Literal["dev", "prod"] = "dev"
    # Labs "publish note as blog": target Astro content repo + layout. Labs-only;
    # defaulted to the author's personal site checkout.
    LUMINARY_BLOG_REPO_PATH: str = "/Users/sethurama/DEV/LM/nupsea.github.io"
    LUMINARY_BLOG_CONTENT_SUBDIR: str = "src/content/blog"
    LUMINARY_BLOG_ASSET_SUBDIR: str = "public/blog"
    LUMINARY_BLOG_BRANCH: str = "master"
    LUMINARY_BLOG_URL_BASE: str = "https://nupsea.github.io"
    OLLAMA_URL: str = "http://127.0.0.1:11434"
    # Keep the Ollama model resident in memory between requests so the first
    # query after an idle period does not re-pay the (large-model) load cost.
    # "-1" = never unload; accepts any Ollama keep_alive value (e.g. "30m").
    OLLAMA_KEEP_ALIVE: str = "30m"
    # Ollama context window. Ollama defaults to 2048 and SILENTLY TRUNCATES
    # longer prompts, so an unset value quietly drops retrieval context. Sized to
    # fit the synthesis prompt budget without waste (prefill time scales with it).
    OLLAMA_NUM_CTX: int = 2048
    # Token budget for retrieved context fed to the synthesis LLM. Prefill time
    # on local models scales ~linearly with prompt size, so this is the primary
    # latency lever. Lower = faster first token, less grounding context. Kept
    # under OLLAMA_NUM_CTX (with headroom for question/system/history) so the
    # prompt is never silently truncated.
    QA_CONTEXT_TOKEN_BUDGET: int = 1500
    LOG_LEVEL: str = "INFO"
    LITELLM_DEFAULT_MODEL: str = "ollama/llama3.2"
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
    # Noise floor for entity-as-tag selection: drop entities mentioned fewer
    # than this many times. Kept LOW (1) so short content (a YouTube transcript
    # mentions a concept once or twice) still surfaces its distinctive concepts.
    # Tag *count* is governed by AUTO_TAG_ENTITY_CAP_MAX + a log-of-chunks
    # budget, not by this floor -- the top-K-by-mention cap is what keeps a long
    # book's central concepts and sheds a short doc's tail.
    AUTO_TAG_ENTITY_MIN_MENTIONS: int = 1
    # Upper bound on entity-derived tags per document. The actual budget scales
    # with chunk count (log) up to this cap, so a book gets dozens, a short
    # transcript a handful.
    AUTO_TAG_ENTITY_CAP_MAX: int = 40
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
