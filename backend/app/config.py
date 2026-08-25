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
    # How long the startup warm-up waits for its one generation.
    #
    # This is NOT an ordinary timeout. A cold model load runs inside that first
    # request, and when the client gives up, httpx closes the connection and
    # Ollama abandons the load outright:
    #
    #   client connection closed before llama-server finished loading, aborting load
    #   Load failed ... error="timed out waiting for llama-server to start: context canceled"
    #
    # So a warm-up that times out does not merely fail to warm anything -- it
    # cancels the load, and the next request starts from nothing. Measured on an
    # Intel i7-8850H in Docker: qwen3.5:4b took just over 60s to load (it is
    # multimodal, so the 3.3GB vision tower and 58 compat tensor transforms load
    # too), against the 60.0s this used to hardcode. The warm-up whose whole
    # purpose is "so the first real question does not pay the load" was the
    # reason the model never finished loading at all.
    #
    # 300s matches Ollama's own OLLAMA_LOAD_TIMEOUT default: the client must
    # never be stricter about a load than the server that performs it.
    LLM_WARMUP_TIMEOUT_SECONDS: float = 300.0
    # Keep the interactive model resident on hosts where a reload is what the
    # user waits for. Warm-up times the first local generation; above the
    # threshold below, `model_keepwarm` pings inside the keep-alive window
    # instead of letting the model be evicted and reloaded on the next question.
    LLM_KEEP_WARM_ENABLED: bool = True
    # Bracketed by two measured start-up probes. Under the line: an Apple
    # Silicon or GPU host, single-digit seconds, which never starts the loop --
    # the point of the threshold, since this must change nothing where nothing
    # is wrong. Over it: an Intel i7-8850H in a 12GB Docker VM, whose start-up
    # probes measured 84.03s, 91.07s and 107.47s, and which later spent 86.25s
    # of one question's 261 loading the model again.
    #
    # The probe is the START-UP generation, not a mid-session sample and not
    # specifically a load. Loads on that host ranged 9.59s-155.45s and did not
    # track page-cache state (35.5s/21.7s with caches dropped against
    # 48.9s/12.7s retained), so a mid-session sample would be a coin toss; and
    # the 91.07s probe paid no load at all -- Ollama never reloaded, the model
    # was resident throughout, and those seconds were start-up contention for 8
    # vCPUs. Both kinds of slowness are the user's wait, so both count.
    # Raising this past a host's start-up probe silently turns the fix off.
    LLM_KEEP_WARM_ABOVE_SECONDS: float = 20.0
    # Comfortably inside OLLAMA_KEEP_ALIVE (30m on every install path this
    # repo controls), so three pings cover a window rather than one racing its
    # edge. A warm ping is one token, ~0.2s on the host above; the cost of
    # getting this wrong in the other direction is a full reload.
    LLM_KEEP_WARM_INTERVAL_SECONDS: float = 600.0
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
    # Admission control: background LLM work yields to interactive work at the
    # granularity of one completed call (Ollama has no preemption). The reserve
    # is derived from OLLAMA_NUM_PARALLEL rather than configured -- at one slot
    # background suspends, at two or more one slot stays free for an Ask. Off
    # only to reproduce the un-gated latency baseline.
    # low | standard | performance, or empty to size from host RAM. Constrains
    # how many models may stay resident and which the registry will recommend.
    # The installer already sizes OLLAMA_MAX_LOADED_MODELS / OLLAMA_NUM_PARALLEL
    # from the same RAM reading and passes them to Ollama too -- this never
    # overrides those, because a backend disagreeing with the runtime about slot
    # count leaves the extra slots idle (I-31). `public` is read as `low`.
    LUMINARY_MEMORY_PROFILE: str = ""
    LLM_ADMISSION_ENABLED: bool = True
    # Hold the reserve this long after an interactive call ends, so a background
    # call is not admitted between two turns of the same conversation.
    LLM_ADMISSION_GRACE_SECONDS: float = 5.0
    # Starvation bound. Someone who keeps chatting must not stop ingestion
    # for ever: a background call held this long is admitted anyway and logged.
    LLM_ADMISSION_MAX_DEFER_SECONDS: float = 60.0
    # How long the user may be left waiting on a background call that is already
    # in flight before it is abandoned. Admission decides whether to *start* one;
    # this covers the case it cannot, where the call was admitted a moment before
    # the question arrived and Ollama will not preempt it (I-31).
    #
    # Bracketed by the two cases that decide it. Under the line: a host where a
    # suggestions call finishes in a couple of seconds -- it completes before the
    # window elapses, so nothing is ever abandoned there and the behaviour is
    # today's exactly. Over it: an Intel i7-8850H in a 12GB Docker VM, where that
    # same call ran 67s (877 prompt tokens, 155 generated) and cost a question
    # 48.5s of its 102s time-to-first-token.
    #
    # Lowering it toward zero would abandon calls on quick hosts too, which
    # spends suggestion quality to buy latency nobody was losing.
    LLM_BACKGROUND_YIELD_AFTER_SECONDS: float = 5.0
    # Token budget for retrieved context fed to the synthesis LLM. Prefill time
    # on local models scales ~linearly with prompt size, so this is the primary
    # latency lever. Lower = faster first token, less grounding context. Kept
    # under OLLAMA_NUM_CTX (with headroom for question/system/history) so the
    # prompt is never silently truncated.
    QA_CONTEXT_TOKEN_BUDGET: int = 1500
    # Prepend each section's generated summary to its chunks in the prompt.
    # Off, and the default is the measurement rather than a preference: the
    # lookup is keyed on (document_id, section_heading), and every retrieved
    # chunk carried an empty heading until that was fixed, so this has never
    # actually fired in a shipped build. Switching it on inflates candidate text
    # by 42.2% and, against QA_CONTEXT_TOKEN_BUDGET, drops the passages that
    # reach the model from 39 to 28 across an 8-query sample -- one query fell
    # from 4 passages to 1. Turning it on means raising the budget with it, and
    # that costs prefill latency and KV cache (I-27).
    QA_ATTACH_SECTION_SUMMARIES: bool = False
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
    # qwen3.5:4b since 2026-08-18. llama3.2 held this by inheritance: it was
    # chosen on an HHEM faithfulness comparison, and a cross-model HHEM delta is
    # a style artifact that may not decide a model. The structural matrix put
    # qwen3.5:4b ahead on all three of its metrics (routing 0.8966 vs 0.8621,
    # card_reject_rate 0.0278 vs 0.0463, generation_rate 1.0000 vs 0.9714), and
    # it reads figures, which is what lets one model serve every role where only
    # one may be resident. Single runs, so this ranks a default, not a swap.
    LITELLM_DEFAULT_MODEL: str = "ollama/qwen3.5:4b"
    # Model for high-quality generation (flashcards, etc).
    # Falls back to DEFAULT_MODEL when empty.
    LITELLM_GENERATION_MODEL: str = ""
    # Model that checks whether a generated card's answer follows from its
    # passage. Empty = the check does not run, and cards are recorded
    # `unchecked` rather than passed. There is deliberately no small-model
    # default: measured on 59 live cards, phi4-mini passed 54 and granite3.2:8b
    # passed 53, agreeing with a 14B on the pass/fail call 0.41 and 0.42 of the
    # time -- a gate built on either certifies exactly what it was added to
    # catch. What re-enables a small checker is a measurement showing it
    # separates supported from unsupported on this corpus, not a smaller model
    # appearing. Must not equal the generation model (self-judging).
    FLASHCARD_FACTUALITY_MODEL: str = ""
    # Prompt arm for the model matrix (P6). `shipped` renders the contract plus
    # the accommodations a model still needs; `bare` renders the contract alone.
    # A model that scores HIGHER on `bare` is telling you the accommodation set
    # is its ceiling. This changes what every generation prompt says, so it is a
    # restart-level knob, and every eval run records the arm that produced it.
    PROMPT_ARM: Literal["shipped", "bare"] = "shipped"
    # Comma-separated accommodation ids to withhold, for the necessity check:
    # drop one, re-measure, and what survives is what `accommodations_needed` on
    # the registry entry should name.
    PROMPT_DROP_ACCOMMODATIONS: str = ""
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
    # qwen3.5:4b since 2026-08-18. It read two real library figures correctly
    # where the 6.81GB qwen2.5vl:7b invented mnemonic expansions on one, and it
    # costs 3.21GB resident with an image loaded -- the same as its text
    # footprint, so on a single-model host vision is free. The dedicated reader
    # stays selectable in Settings and is honoured when chosen.
    #
    # n=2 figures. Enough to stop paying 6.81GB for a second model by default;
    # not a finding that the specialist is worse. A larger figure sample is the
    # measurement that would settle it either way.
    VISION_MODEL: str = "ollama/qwen3.5:4b"
    # How long the vision runner stays resident after its last image, overriding
    # OLLAMA_KEEP_ALIVE for this path only. The vision model is the largest thing
    # Luminary loads (~6GB for a 7B VLM) and it is used in bursts: a document's
    # figures, then nothing until the next upload. Inheriting the global 30m held
    # that 6GB for half an hour after enrichment drained, which is what put a
    # 16GB machine into swap. Long enough to serve a run of images back to back,
    # short enough to release soon after; "0" would unload between every image
    # and pay the reload each time. Not a num_ctx change, so I-27 is untouched.
    VISION_KEEP_ALIVE: str = "60s"
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
    # The entity model, and the second-largest thing Luminary loads (1126MB).
    # Turning it off is not the memory lever it looks like: `graph_expand` in
    # retriever_strategies skips query expansion whenever this model is not
    # resident, so an unloaded entity model silently changes retrieval rather
    # than only freeing memory. A smaller model that stays resident is therefore
    # worth more than a large one that does not.
    #
    # The default is `gliner_multi-v2.1` fine-tuned onto a synthetic PII dataset
    # and six languages, while ENTITY_TYPES in ner.py asks for PERSON,
    # ORGANIZATION, CONCEPT, TECHNOLOGY, ALGORITHM and friends -- none of which
    # is PII. Whether a smaller general model is better here as well as lighter
    # is measured by `scripts/ner_compare.py`, not assumed; the default stays put
    # until those numbers say otherwise.
    NER_MODEL: str = "urchade/gliner_multi_pii-v1"
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
