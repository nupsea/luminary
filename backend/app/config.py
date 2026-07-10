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
    # Larger context for heavy one-shot tasks (flashcard generation feeds a whole section, up to
    # _CHUNK_CHAR_LIMIT chars ~= 2.5k tokens, plus system + output). At 2048 these were silently
    # truncated and the model emitted junk; generation passes this instead.
    OLLAMA_GENERATION_NUM_CTX: int = 8192
    # Token budget for retrieved context fed to the synthesis LLM. Prefill time
    # on local models scales ~linearly with prompt size, so this is the primary
    # latency lever. Lower = faster first token, less grounding context. Kept
    # under QA_NUM_CTX (with headroom for question/system/history) so the
    # prompt is never silently truncated.
    QA_CONTEXT_TOKEN_BUDGET: int = 1500
    # Context window for the QA/chat streaming call. num_ctx bounds prompt AND
    # generation combined: the QA prompt alone can reach ~1900 tokens (1500
    # chunk budget + up to 1000-token section_context + system + history), and
    # the answer carries a trailing citations JSON with excerpts. At 2048 the
    # generation hit done_reason=length mid-JSON, losing answers entirely.
    QA_NUM_CTX: int = 4096
    # L2 funnel: how many RRF candidates the cross-encoder re-scores. HR@k of
    # the reranked list is bounded by HR@depth of the RRF pool, so depth is the
    # recall lever L2 owns; cross-encoder latency scales linearly with it
    # (~5ms/pair CPU). Tune via evals `--rerank-depths` sweep before changing.
    RERANK_DEPTH: int = 50
    # L2 funnel: minimum cross-encoder logit to keep a candidate (ms-marco
    # MiniLM logits are unbounded, roughly -11..+11; relevant pairs usually
    # score > 0). None/unset = no cut. The top candidate always survives so a
    # strict threshold degrades context, never empties it.
    RERANK_SCORE_THRESHOLD: float | None = None
    # L2 funnel: convex blend of RRF and cross-encoder scores when reranking.
    # final = alpha*norm(RRF) + (1-alpha)*norm(CE). Guards a confident RRF hit
    # from a weak CE demotion (the MiniLM CE nets NEGATIVE HR@5 on some sets).
    # None/0 = pure CE. 1 = pure RRF (no rerank effect). 0.7 chosen by sweep:
    # HR@5 >= both rrf and pure-CE on iceberg/d2l/time_machine, best avg HR@5
    # (.70) + MRR (.57), and it fixes the pure-CE negative-rerank regression on
    # time_machine (.567 -> .700). Heavy RRF weight reflects a weak MiniLM CE.
    RERANK_BLEND_ALPHA: float | None = 0.7
    LOG_LEVEL: str = "INFO"
    LITELLM_DEFAULT_MODEL: str = "ollama/llama3.2"
    # Model for high-quality generation (flashcards, etc).
    # Falls back to DEFAULT_MODEL when empty.
    LITELLM_GENERATION_MODEL: str = ""
    # Opt-in: Phoenix is a dev observability server (launches on :6006, persists
    # phoenix.db, instruments every LLM call). A local-first/offline runtime
    # shouldn't pay that cost or its serializer noise by default — set
    # PHOENIX_ENABLED=true in .env when you want tracing.
    PHOENIX_ENABLED: bool = False
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
