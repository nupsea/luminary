import functools
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

from app.paths import app_root, is_packaged

# An `.env.example` placeholder that no install script rendered.
_PLACEHOLDER_RE = re.compile(r"@@[A-Z0-9_]+@@")


def _env_files() -> tuple[str, ...]:
    """Env files in ascending precedence -- pydantic-settings lets the last win.

    ``.env`` is resolved against the process working directory, which is a
    landmine for any GUI-launched process (macOS hands those CWD=/). Callers
    that cannot control the working directory should set LUMINARY_ENV_FILE to an
    absolute path instead, which is why it sits last.
    """
    files = [".env", "/app/.luminary/.env"]
    explicit = os.environ.get("LUMINARY_ENV_FILE", "").strip()
    if explicit:
        files.append(explicit)
    return tuple(files)


class Settings(BaseSettings):
    # Relative values resolve against the repo root, NOT the CWD: scripts run
    # from backend/ used to silently create a stray backend/.luminary store.
    DATA_DIR: str = ".luminary"
    # full: every surface on, routers at root, CORS open for the Vite dev server
    #       (`make luminary`). public: curated learner surfaces only, built SPA
    #       served with the API under /api on one port (no CORS).
    LUMINARY_MODE: Literal["full", "public"] = "full"
    # "Publish note as blog": target Astro content repo + layout. Full-mode-only.
    # Unset by default -- these ship to every installed copy, so they must not
    # carry a developer's home path or site, and an empty repo path leaves the
    # feature inert until a user deliberately points it somewhere.
    LUMINARY_BLOG_REPO_PATH: str = ""
    LUMINARY_BLOG_CONTENT_SUBDIR: str = "src/content/blog"
    LUMINARY_BLOG_ASSET_SUBDIR: str = "public/blog"
    LUMINARY_BLOG_BRANCH: str = "master"
    LUMINARY_BLOG_URL_BASE: str = ""
    OLLAMA_URL: str = "http://127.0.0.1:11434"
    # Keep the Ollama model resident in memory between requests so the first
    # query after an idle period does not re-pay the (large-model) load cost.
    # "-1" = never unload; accepts any Ollama keep_alive value (e.g. "30m").
    OLLAMA_KEEP_ALIVE: str = "30m"
    # Ollama context window, and the ONLY one: this is a per-model property, not
    # a per-call one. Ollama keys a loaded runner on num_ctx, so a call asking
    # for a different window unloads llama-server and reloads it -- tens of
    # seconds, on the critical path. Three call-site-specific values (2048 chat
    # default, 4096 QA, 8192 generation) meant one chat turn reloaded the model
    # twice, and any turn overlapping enrichment reloaded it repeatedly. Sized
    # for the largest single prompt (flashcard generation feeds a whole section,
    # up to _CHUNK_CHAR_LIMIT chars ~= 2.5k tokens, plus system + output);
    # anything smaller silently truncates that prompt. Lowering this to save
    # memory only helps if it stays one value -- per-call windows cost far more
    # in reloads than they save in KV cache.
    OLLAMA_NUM_CTX: int = 8192
    # Also caps the enrichment semaphores: past the slot count calls queue in
    # Ollama rather than overlap (I-31). Costs one KV cache per slot, so 1 is
    # the floor for an unmeasured machine; installers raise it from host RAM.
    OLLAMA_NUM_PARALLEL: int = 1
    # Token budget for retrieved context fed to the synthesis LLM. Prefill time
    # on local models scales ~linearly with prompt size, so this is the primary
    # latency lever. Lower = faster first token, less grounding context. Kept
    # under OLLAMA_NUM_CTX (with headroom for question/system/history) so the
    # prompt is never silently truncated.
    QA_CONTEXT_TOKEN_BUDGET: int = 1500
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
    # final = alpha*norm(RRF) + (1-alpha)*norm(CE); None = pure CE. The blend
    # existed to guard against a weak CE demoting confident RRF hits, but the
    # 12-doc model x alpha sweep showed the guard is compensation for a weak
    # model: with L-12, alpha 0/.2/.3 are indistinguishable (.693/.690/.691)
    # and pure CE is best + simplest. Kept as a per-request knob
    # (/search?rerank_blend=) for experiments, off by default.
    RERANK_BLEND_ALPHA: float | None = None
    # Cross-encoder for L2 reranking. L-12 chosen by the 12-doc sweep: best
    # mean HR@5 (.693 vs L-6-best .688), passes the "no dataset >1 question
    # below no-rerank" constraint that every low-alpha L-6 config fails
    # (time_machine -2q), and fixes hamlet (.567 -> .667). Cost: rerank adds
    # ~510ms/query on CPU vs ~250ms for L-6 -- quality/safety over speed.
    RERANK_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"
    # Signal-adaptive blend: treat RERANK_BLEND_ALPHA as a CEILING and scale the
    # actual blend by cross-encoder confidence per query (guard-when-CE-weak).
    # Off by default while it's a prototype under evaluation.
    RERANK_BLEND_ADAPTIVE: bool = False
    # Correct out-of-corpus query tokens to their nearest corpus token before
    # retrieval (fixes typo'd proper nouns that collapse corpus-wide search to
    # the wrong documents). Proven safe: full typo recovery, zero clean-query
    # regression. Per-request override via /search?spell_correct=.
    QUERY_SPELL_CORRECT: bool = True
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
    VISION_MODEL: str = "ollama/qwen2.5vl:7b"
    # Max concurrent vision (image_analyze) LLM calls across all documents. Default
    # 1 = one-at-a-time (safe on 8GB). Raise (e.g. 2-4) on a host with headroom and
    # pair with OLLAMA_NUM_PARALLEL so a single Ollama batches the calls. The install
    # profile sets this: public=1, standard=2, performance=4.
    ENRICHMENT_VISION_CONCURRENCY: int = 1
    # Rasterize vector-drawn PDF figures when a page has no embedded raster image.
    # LaTeX-authored papers draw figures with path operators, so without this they
    # extract zero images. Costs a vision LLM call per recovered figure — turn off
    # on a machine where enrichment throughput matters more than figure coverage.
    PDF_VECTOR_FIGURES: bool = True
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
    # One LLM call per section, so uncapped scales with the book (DDIA's 200
    # sections = ~50min). 0 means uncapped, not disabled.
    WEB_REFS_MAX_SECTIONS: int = 40
    BRAVE_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    ADMIN_KEY: str = ""
    PHOENIX_GRPC_PORT: int = 4317

    # extra="ignore": `.env` outlives the binary reading it. The "forbid"
    # default makes a key from another version a refuse-to-start.
    model_config = {
        "env_file": _env_files(),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @model_validator(mode="before")
    @classmethod
    def _drop_unrendered_placeholders(cls, values: Any) -> Any:
        """Treat an unrendered `@@NAME@@` template value as unset.

        Its placeholders land on typed fields, so a hand-copied `.env.example`
        would otherwise refuse to start. A genuine typo still fails.
        """
        if not isinstance(values, dict):
            return values
        return {
            k: v
            for k, v in values.items()
            if not (isinstance(v, str) and _PLACEHOLDER_RE.fullmatch(v.strip()))
        }

    @field_validator("DATA_DIR")
    @classmethod
    def _anchor_relative_data_dir(cls, v: str) -> str:
        p = Path(v).expanduser()
        resolved = p if p.is_absolute() else (app_root() / p).resolve()

        # In a packaged app the resource root is read-only, code-signed, and
        # replaced wholesale on upgrade. A library resolving inside it would be
        # unwritable at best and silently destroyed by the next update at worst,
        # so refuse to start rather than take that path.
        if is_packaged() and resolved.is_relative_to(app_root()):
            raise ValueError(
                f"DATA_DIR ({resolved}) resolves inside the application bundle "
                f"({app_root()}). Set DATA_DIR to an absolute path outside it."
            )
        return str(resolved)


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
