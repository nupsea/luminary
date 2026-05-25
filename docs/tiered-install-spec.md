# Tiered install profile — engineering spec (Phase 3, Track 1.5)

Status: spec + implementation in progress
Drafted: 2026-05-24
Owner docs: `docs/phase-3-plan.md` (Track 1, Track 3.3), `docs/labs-drawer-spec.md`

> The labs-drawer spec gates *UI surfaces and route/router registration*. It does not change what gets **installed**. On a local-first app the footprint is dominated by Python ML wheels and Ollama models, neither of which the manifest touches today. This spec adds a second axis — the **install profile** — using the same `public | labs | dev` tier vocabulary, so a learner install is small enough for an average laptop while `labs`/`dev` remain one flag away.

---

## The problem, measured

Three cost surfaces, wildly unequal:

| Surface | Magnitude | Gated by labs-drawer manifest? |
|---|---|---|
| Frontend JS bundle | single-digit MB | Yes (build-time strip) — cheapest surface |
| Python deps (`uv sync`) | ~2-4 GB installed | **No** — `pyproject.toml` is monolithic |
| Ollama models | **9-15 GB** | **No** — pulled outside the app |

Observed defaults: `gemma4` ≈ 9.6 GB, `llava:7b` ≈ 4.7 GB. Stripping dev JavaScript saves megabytes; the laptop pain is gigabytes of models and ML wheels. Therefore the install profile, not the bundle strip, is what makes "runs on a student laptop" true.

### Dependency-to-tier map

**Public core (the learner floor):**
- LLM via Ollama/LiteLLM (`LITELLM_DEFAULT_MODEL`)
- Embeddings: `bge-small-en-v1.5`, ~133 MB, auto-downloaded on first use (`services/embedder.py`)
- Deps: fastapi/uvicorn, sqlalchemy+aiosqlite, lancedb, kuzu, sentence-transformers, langgraph, langchain-text-splitters, pymupdf/ebooklib/python-docx, fsrs, genanki, numpy, optimum[onnxruntime], pillow
- GLiNER: semi-core (NER, graph entities, prerequisites, confusion detection). Kept in base; gated at runtime by `GLINER_ENABLED` for low-RAM machines. Model ~0.5-1 GB on first use.

**`labs` adds:**
| Feature (manifest id) | Heavy dep | Added cost |
|---|---|---|
| `audio_transcribe` | `faster-whisper` | wheel + `base` model ~150 MB |
| `youtube_ingest` | `yt-dlp` | small wheel |
| `code_parsing` | `tree-sitter` + 5 grammars | ~tens of MB |
| `clustering_orgplan` | `scikit-learn` | ~30-100 MB |
| `web_search` | `trafilatura`, `cloudscraper` | small |
| `image_enrichment` | Pillow (base) + `llava:7b` model | **4.7 GB model** — largest single labs cost |

**`dev` adds:**
- `arize-phoenix` (heavy), `langfuse`, `reportlab`, plus pytest/ruff/tiktoken/psutil tooling.

---

## Design decisions (locked)

1. **Two axes, one vocabulary.** The labs-drawer manifest controls *visibility* (what UI/routes exist at runtime). The install profile controls *presence* (what wheels and models are on disk). Both use `public | labs | dev`. They are independent: a `public` install can still ship labs *code* (gated off) but not labs *deps*.

2. **Both `labs` and `dev` are PEP 735 dependency-groups.** General packaging guidance favours extras for shippable feature sets, but this app is run **from source via uv**, never `pip install`ed as a published package — so the extras-vs-groups semantics matter less than install ergonomics. The deciding factor: uv 0.8.x has no `default-extras` knob (only `default-groups`), so only dependency-groups can be made to install-by-default for the author while opting out cleanly for the public install. Groups give exactly that.

3. **Labs code must import heavy deps lazily.** Because labs *code* ships in a `public` install but its *deps* do not, every labs service imports its heavy dependency **inside the function that uses it**, never at module top. Invoking a labs feature whose extra is not installed raises a clear actionable error, not an `ImportError` at boot. This matches the existing pattern (`ruff` ignores `PLC0415` — "lazy-loading pattern is intentional").
   - Audit status: `audio_transcriber`, `youtube_downloader`, `code_parser`, `clustering_service`, `web_searcher`, `reference_enricher` already lazy. `image_enricher` imports `PIL` at top level — acceptable, Pillow stays in base. `phoenix` (`telemetry.py:87`) and `langfuse` (`services/llm.py:50`) already lazy and guarded by `PHOENIX_ENABLED`.
   - **Fixed:** `services/article_extractor.py` imported `cloudscraper`/`trafilatura` at module top and is pulled in by the public `documents` router (`documents.py:68`) — this broke `import app.main` on the public profile. Now lazy via `require_extra` (`app/labs_extras.py`). Consequence: **URL article ingestion is now effectively labs-gated** — on a public install, ingesting a URL raises the actionable error. The surface manifest should map URL/web ingestion to `labs` accordingly.

4. **Models are pulled on demand, never bundled.** The installer pulls the LLM; `bge-small` and GLiNER auto-download on first use. `llava:7b` is pulled only when `image_enrichment` labs is enabled. No multi-GB weights baked into any installer or bundle.

5. **The public default model is a quantized small model.** A 3-4B GGUF at `Q4_K_M` (~2-3 GB) is the public default — ~95% quality at ~25% memory, and already beats API round-trips for summarization/classification/FAQ-style QA, which is most of the learner loop. Larger models are offered via Settings, not shipped by default.

---

## Mechanism

### `pyproject.toml`

```toml
[project]
dependencies = [ ...public core only... ]   # scikit-learn dropped: pulled transitively by sentence-transformers

[dependency-groups]
labs = [
  "faster-whisper>=1.2.1",
  "yt-dlp>=2026.3.13",
  "tree-sitter>=0.25.2",
  "tree-sitter-go>=0.25.0",
  "tree-sitter-javascript>=0.25.0",
  "tree-sitter-python>=0.25.0",
  "tree-sitter-rust>=0.24.0",
  "tree-sitter-typescript>=0.23.2",
  "trafilatura>=2.0.0",
  "cloudscraper>=1.2.71",
]
dev = [ ...tooling..., "arize-phoenix>=13.3.0", "langfuse>=3.14.5" ]

[tool.uv]
default-groups = ["dev", "labs"]   # author's dev tier installs everything by default
```

### Install profiles (uv invocations)

| Profile | Command | Gets |
|---|---|---|
| `dev` (author daily, CI) | `uv sync` | base + labs + dev (both default-groups) = everything |
| `labs` (QA/preview) | `uv sync --no-default-groups --group labs` | base + labs, no dev observability |
| `public` (learner install) | `uv sync --no-default-groups` | base only |

Because both `labs` and `dev` are in `default-groups`, the existing `make ci` / `make luminary` / `uv run` paths keep working unchanged — `uv sync` and `uv run` both honour `default-groups`. Only `scripts/install.sh` (Track 3.3.C) opts down to the public profile with `--no-default-groups`.

> `scikit-learn` cannot be excluded from the public install — `sentence-transformers` (base) requires it transitively. The `clustering_orgplan` labs feature relies on it, but its presence is guaranteed regardless of tier, so it is not listed in the `labs` group and is gated only at the manifest/UI level.

### Runtime guard for missing extras

A small helper raises a uniform error when a labs feature is invoked without its extra:

```python
def require_extra(module: str, feature: str) -> None:
    import importlib.util
    if importlib.util.find_spec(module) is None:
        raise RuntimeError(
            f"{feature} requires the 'labs' dependency group. "
            f"Reinstall with: uv sync --group labs"
        )
```

Called at the top of each labs service's entry function, before the lazy import.

### Model pulls (`scripts/install.sh`, Track 3.3.C)

- Always: pull the public default LLM (quantized 3-4B).
- `bge-small`, GLiNER: no pull — auto-download on first use into `DATA_DIR/models`.
- `llava:7b`: pulled only when `image_enrichment` is enabled (labs).
- The model list is derived from the surface manifest's enabled tiers, keeping single-source-of-truth.

---

## Verification (done bar)

- `uv sync --no-default-groups` produces an environment with **no** `arize-phoenix`, `langfuse`, `faster-whisper`, `yt-dlp`, `tree-sitter*`, `trafilatura`, `cloudscraper` (verified: 17 direct labs/dev packages plus transitives removed). `scikit-learn` remains — transitive via `sentence-transformers`.
- Booting the backend in that environment with `LUMINARY_SURFACE_TIER=public` starts cleanly — no `ImportError` — and serves the public routers.
- Invoking a labs endpoint in that environment returns the `require_extra` actionable error, not a 500 traceback.
- `uv sync` (default) still installs everything; `make ci` passes unchanged.
- A public install (small quantized LLM + bge-small + base deps) totals roughly **3-4 GB**, down from ~16-18 GB.

---

## Implementation status

- **Done (this pass):** dependency split in `backend/pyproject.toml` (`labs` + `dev` as PEP 735 groups, `default-groups = ["dev", "labs"]`); `require_extra` helper (`app/labs_extras.py`); lazy-import fix in `article_extractor.py`. Verified: default `uv sync` keeps the full dev tier; `uv sync --no-default-groups` sheds 17 labs/dev packages + transitives; `import app.main` succeeds on both tiers; ruff clean; all 1674 tests collect; article/extract tests pass.
- **Done (CI guard):** `scripts/check_public_import.sh` syncs an isolated public-profile env and asserts `import app.main` succeeds under `LUMINARY_SURFACE_TIER=public`; wired into `make ci` (between `boundary_checker` and `pytest`). Runs on GH Linux + Apple Silicon; the Intel-Mac Docker CI branch does not invoke it (known gap).
- **Next:** wire the public profile into `scripts/install.sh` (Track 3.3.C) with tiered model pulls; set the public default to a quantized 3-4B GGUF; extend the surface manifest to map URL/web ingestion to `labs`.

## Out of scope

- Per-extra granularity below `labs` (e.g. installing only `audio_transcribe`). One `labs` extra is sufficient for v1.
- Bundling models into the Tauri artifact (Track 3.3.E) — models are always fetched on first run.
- GPU/CUDA wheel variants — CPU-first, local-laptop target.
