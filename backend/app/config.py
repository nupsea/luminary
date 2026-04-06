import functools

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATA_DIR: str = ".luminary"
    OLLAMA_URL: str = "http://localhost:11434"
    LOG_LEVEL: str = "INFO"
    LITELLM_DEFAULT_MODEL: str = "ollama/mistral"
    PHOENIX_ENABLED: bool = True
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    WHISPER_MODEL_SIZE: str = "base"
    VISION_MODEL: str = "ollama/llava:13b"
    GLINER_ENABLED: bool = True  # Set to false on memory-constrained machines (avoids OOM)
    WEB_SEARCH_PROVIDER: str = "none"  # "none" | "brave" | "tavily" | "duckduckgo"
    BRAVE_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    ADMIN_KEY: str = ""

    model_config = {"env_file": (".env", "/app/.luminary/.env"), "env_file_encoding": "utf-8"}


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
