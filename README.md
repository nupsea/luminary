# Luminary

**Study smarter, locally.** Upload a book or paper, ask questions with source citations, and review with FSRS-scheduled flashcards — your data never leaves your machine.

> Local-first document learning with cited Q&A and science-backed spaced repetition.

No subscription. No cloud sync. Works offline with a local LLM (Ollama) or any API key you supply.

**[Watch the intro video](https://youtu.be/semZlbJde_Q)** — a tour of Luminary.

---

## Install and run

### macOS (Apple Silicon) — download the app (recommended)

The simplest way in. Download `Luminary_<version>_aarch64.dmg` from the
[latest release](https://github.com/nupsea/luminary/releases/latest), open it, and
drag Luminary to your Applications folder.

There is nothing else to install. The Python runtime, every dependency and the
local inference server all live inside the app — no terminal, Homebrew, Node or
separate Ollama. Requires macOS 14 (Sonoma) or newer on Apple Silicon.

The download is about 700 MB. First launch fetches roughly 1.4 GB of models; your
library opens after about 20 seconds and the rest finishes in the background,
typically inside two minutes. A chat model is a separate ~2 GB download that the
app offers when you first need one — everything else works without it.

Your library is kept in `~/Library/Application Support/sh.luminary.app/`.

**If it will not start,** the startup screen says what went wrong and can open a
pre-filled bug report. Nothing is sent anywhere until you have read it and
submitted it yourself. There is also a log at
`~/Library/Logs/Luminary/luminary.log`.

**To remove it,** drag Luminary from Applications to the Trash. That leaves your
library untouched; if you want that gone too, delete
`~/Library/Application Support/sh.luminary.app/` as well.

### macOS (Apple Silicon) — one command

Choose this instead if you want Luminary running as a background service with a
command-line tool, or if you already have a `~/.luminary` library from a source
install and want to keep using it.

The two installs are independent. They keep separate libraries — the app's under
Application Support, this one at `~/.luminary` — and neither reads the other's, so
pick one rather than running both.

> **Beta.** This installer is new and has not yet been tested across a wide range
> of Macs. If it fails, use the source install below and please
> [open an issue](https://github.com/nupsea/luminary/issues) — it registers a
> background service, so `luminary uninstall` cleanly reverses it.

```bash
curl -fsSL https://raw.githubusercontent.com/nupsea/luminary/master/scripts/bootstrap.sh | bash
```

Starts Luminary at login and opens it in your browser. No Homebrew, Node, git or
Xcode tools required.

The application installs to `~/Library/Application Support/Luminary` while your
library stays at `~/.luminary`, so upgrades never touch your data.

Requires macOS 14 (Sonoma) or newer. The first install downloads roughly 5GB of
models and takes 15-25 minutes.

Manage it with the `luminary` command (installed to `~/.local/bin`):

```bash
luminary status      # version, paths, service and Ollama state
luminary stop        # stop the background service
luminary update      # upgrade in place; your library is preserved
luminary uninstall   # remove the app; asks before touching your library
```

### Linux & WSL — from source
A stock Ubuntu image ships none of `git`, `make` or `curl`, so install those first:
```bash
sudo apt-get update && sudo apt-get install -y git make curl
git clone https://github.com/nupsea/luminary.git
cd luminary
make install   # Installs uv, Node, Ollama; pulls models; builds the app
make start     # Starts the production server on http://localhost:7820
```
`make install` needs `sudo` once, for Ollama and for the `zstd` its installer
requires. Node is fetched into `~/.local` — apt only carries Node 18 and the
build needs 20+, so the installer does not use apt for it.

Verified end to end on a clean `ubuntu:24.04` container (arm64).

### macOS (Intel / x86_64) — via Docker
Intel Macs have no native `lancedb` wheel, so the native `make install` can't run there.
Use Docker instead:
```bash
git clone https://github.com/nupsea/luminary.git
cd luminary
docker compose --profile ai up   # or: make docker-run
```
Then open http://localhost:7820. (Apple Silicon Macs use the native path above.)

### Windows — Docker
```powershell
docker compose --profile ai up
```
Needs [Docker Desktop](https://www.docker.com/products/docker-desktop/) running. Open http://localhost:7820 when the log settles.

### Windows — native (behind a proxy/VPN that blocks Docker)
Install once, then start whenever you want it. In a normal PowerShell window (no admin):
```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; .\scripts\install.ps1   # one-time setup; creates start.ps1
.\start.ps1                                                                # run this each time
```
Wait for `Luminary is ready`, then open http://localhost:7820. The first start downloads models, so give it a few minutes — the launcher tells you when it's done.

> First launch is slow because it downloads ML models. All launchers poll the server and print `Luminary is ready` only when it truly is; until then they say models are still downloading. Background `Warmup:` log lines after that are normal.

---

## Your first 5 minutes

1. **Add a source** — Library → Upload a PDF, EPUB, doc or media file, or paste a web-article or YouTube URL
2. **Wait for processing** — a summary card appears when indexing finishes (usually under a minute)
3. **Ask a question** — Ask tab → citations link straight back to the source section
4. **Review flashcards** — Study → Start Review → grade cards; FSRS schedules the next one

That's the core loop. Luminary adds more as you return: mastery rings on the library card, a "What's about to slip" widget, reading continuity ("Continue reading" picks up exactly where you left off), a references panel per section, and a prediction-calibration graph on Progress.

---

## Features

### Cited Q&A — Ask across your library

Chat with every document you've uploaded. Every answer includes citations with section heading, excerpt, and page number.

Press **⌘K** from any tab to open the Quick Ask panel. Toggle **Socratic mode** (default) to get a probing question before the answer — useful for active recall. If a question fails (model busy, briefly offline), retry it inline without retyping.

### Spaced repetition — Remember what you read

AI-generated flashcards (regular, cloze-deletion, code-trace) scheduled by the FSRS algorithm. Review sessions are shaped into three phases:

- **Warm-up** — well-retained cards to build momentum
- **Engage** — cards that need work
- **Reflect** — phase label on the last 15%

Before flipping a card, predict your confidence (Know it / Unsure / Blank). Luminary tracks your prediction accuracy on the Progress tab.

### Local-first reader — Read and annotate

Side-by-side PDF viewer with section navigation and an optional dark-page mode for low-glare reading. Jump to a page by typing its number or with arrow-key navigation. Luminary saves your reading position; "Continue reading" brings you back to the right section. Generate flashcards from a text selection, or delete a document straight from the reader header. Web articles and papers keep their figures inline, with extracted text cleaned up on the way in.

### Media & web — Learn from more than PDFs

Paste a **web article** or **YouTube** URL and Luminary mirrors the content, transcribes or extracts it, and indexes it like any other source. Drop in **audio or video** files and it transcribes them; import **Kindle clippings** to turn highlights into a studyable document. Research papers get structure-aware chunking so sections and figures survive ingestion.

### Works offline — No internet required

With a local model (Ollama), the whole loop runs with no connection. If you go offline mid-session, Luminary keeps working and routes Ask to the local model with a clear notice instead of failing.

### References — Canonical sources per section

Every document section gets a **References** panel with LLM-suggested canonical sources: official docs for software, Stanford Encyclopedia of Philosophy for philosophy, PubMed for science, and so on. Click any reference to open it; outdated references can be refreshed per-section.

### Notes — Write alongside reading

Markdown editor with live preview. Notes are indexed and appear in search. Supports Mermaid diagrams and Excalidraw sketches.

### Progress — See what's sticking

- Mastery rings on every document card (weighted FSRS stability)
- "What's about to slip" widget (cards approaching the forgetting threshold)
- Study activity chart (last 30 days)
- Prediction calibration graph (are your confidence ratings accurate?)
- Sort library by "Weakest first" to target the documents that need the most work

### Hub — Your daily learning cockpit

The home screen surfaces the day's highest-leverage action (review due cards, continue reading, or take a note) and shows your most active projects with due-card counts. Collections keep related documents grouped; clicking one opens a focused study environment scoped to that project.

---

## Models

If the app warns that Ollama isn't running or no model is pulled, only the LLM features (chat, teach-back, flashcards) pause — everything else keeps working. Fix it with `ollama serve` and `ollama pull llama3.2` (Docker users: the `--profile ai` sidecar does this automatically on first start).

Luminary defaults to **Llama 3.2** via Ollama (pulled by `make install`).

| Model | Command | Best for | RAM/VRAM |
|-------|---------|----------|------|
| Llama 3.2 3B (default) | `ollama pull llama3.2` | Everyday use, lightweight laptops | ~2 GB |
| Gemma 3 4B | `ollama pull gemma3:4b` | Strong reasoning at a small size | ~4 GB |
| Llama 3.1 8B | `ollama pull llama3.1` | A step up in quality | ~5 GB |
| Qwen 2.5 14B | `ollama pull qwen2.5:14b-instruct` | Highest quality, needs more memory | ~9 GB |

Any Ollama-served chat model works — these are just tested starting points. `llama3.2` is the default because it was the fastest and most faithful of the small models on our eval harness.

### How to switch to other models

To use a different local model:
1. Pull the desired model via Ollama (e.g., `ollama pull gemma3:4b`).
2. Add or update `LITELLM_DEFAULT_MODEL` in `backend/.env` (prefixed with `ollama/`):
   ```bash
   LITELLM_DEFAULT_MODEL=ollama/gemma3:4b
   ```

### Switch to a cloud model (optional)

Create or update `backend/.env`:

```bash
# OpenAI
LITELLM_DEFAULT_MODEL=openai/gpt-4o
OPENAI_API_KEY=sk-...

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
LITELLM_DEFAULT_MODEL=anthropic/claude-3-7-sonnet-latest

# Google
LITELLM_DEFAULT_MODEL=gemini/gemini-2.5-pro
GOOGLE_API_KEY=...
```

---

## Configuration

All settings are environment variables in `backend/.env` (gitignored).

| Variable | Default | Description |
|----------|---------|-------------|
| `LITELLM_DEFAULT_MODEL` | `ollama/llama3.2` | LLM for chat, summaries, flashcards |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama server address |
| `VISION_MODEL` | `ollama/qwen2.5vl:7b` | Model for image/figure analysis (optional, full mode only) |
| `PDF_VECTOR_FIGURES` | `true` | Rasterize vector-drawn PDF figures (LaTeX papers embed no images) |
| `LUMINARY_MODE` | `full` | `full` = every feature (what `make luminary` runs); `public` = curated learner surfaces, SPA + API on one port |
| `GLINER_ENABLED` | `true` | Entity extraction (disable on <8 GB RAM) |
| `DATA_DIR` | `.luminary` | Where databases and embeddings live |

---

## Your data

Everything — library database, vector embeddings, knowledge graph, notes — is in `.luminary/` at the project root. To move to a new machine: copy `.luminary/`, `DATA/` (source files), and `backend/.env`.

The library database schema is versioned with Alembic, and the server applies any pending migrations on startup. Upgrading Luminary keeps your existing library, flashcards and review history — you never need to delete the database to take a new version.

Export options: Markdown vault (Obsidian-compatible), Anki deck (`.apkg`), flashcard CSV.

### Re-extracting figures from an existing document

Extraction improvements only apply to documents ingested after them. To re-run
figure extraction on a document already in your library, without re-uploading it:

```bash
curl -X POST http://localhost:7820/documents/<document_id>/images/reextract
```

Extraction deduplicates on content hash, so this only adds figures the previous
run missed. `GET /documents/<document_id>/enrichment` shows the job's progress.

---

## Make commands

| Command | What it does |
|---------|-------------|
| `make install` | One-time setup (uv, Node, Ollama, models, build) |
| `make start` | Start the public-mode server on :7820 (curated learner surfaces) |
| `make luminary` | Start backend + frontend in full mode (:7820 + :5173) — every feature enabled |
| `make stop` | Stop all Luminary processes |
| `make test` | Unit + integration tests |
| `make lint` | Ruff + tsc |
| `make ci` | Full CI: deps, lint, layer check, tests, build |
| `make db-migrate` | Apply pending database migrations (the server also does this on boot) |
| `make db-revision m="..."` | Generate a migration after changing `models.py` |
| `make docker-build` | Build the Docker image |
| `make docker-run` | Run via Docker Compose (with Ollama sidecar) |

---

## Evaluation harness

Luminary ships a retrieval and generation eval harness with golden Q&A datasets. Retrieval is scored with HR@5 / MRR / nDCG@10; faithfulness uses a dedicated NLI model (Vectara HHEM-2.1-Open) rather than an LLM judge, so it is deterministic and needs no API key. An optional `--judge-model` adds answer relevance. See [`evals/README.md`](evals/README.md) for the full picture.

```bash
cd evals && uv run python run_eval.py --dataset book --backend-url http://localhost:7820
```

Enforced thresholds: HR@5 ≥ 0.60, MRR ≥ 0.45. Faithfulness is currently **report-only** — the metric moved from an LLM judge to NLI, so its old floor no longer applies and a new one has yet to be derived from a labelled run.

---

## Platform notes

| Platform | Status |
|---------|--------|
| macOS Apple Silicon | Native, fully supported |
| macOS Intel | Docker required for backend (auto-detected by `make luminary`) |
| Linux / WSL | Native, same steps |
| Windows | Supported via Docker (Docker Desktop) or natively via `scripts/install.ps1` |

---

## Architecture (for contributors)

```
Types -> Config -> Repo -> Service -> Runtime -> API
         (6-layer dependency rule — no reverse imports)
```

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.13, FastAPI, LangGraph, LiteLLM |
| Storage | SQLite (metadata), LanceDB (vectors), Kuzu (graph), FTS5 |
| ML | BAAI/bge-small-en-v1.5 embeddings, GLiNER (zero-shot NER), ms-marco-MiniLM cross-encoder reranker |
| Retrieval | RRF hybrid (vector + BM25 + graph traversal), then cross-encoder rerank |
| Spaced rep | FSRS algorithm |
| Frontend | React, TypeScript, Vite, shadcn/ui, Tailwind CSS (versions in `frontend/package.json`) |
| Graph viz | Sigma.js v3 + Graphology |
| State | Zustand + TanStack Query |

```
backend/app/
  config.py       Settings
  models.py       SQLAlchemy ORM
  services/       Business logic (one file per domain)
  routers/        FastAPI endpoints
  runtime/        LangGraph workflows, background workers
  workflows/      Ingestion pipeline

frontend/src/
  pages/          Tab-level components
  components/     Reusable UI
  store/          Zustand stores
  lib/            Utilities, API client
  hooks/          Custom React hooks
```

### Documentation

- **[DEEP_DIVE.md](DEEP_DIVE.md)** — the long-form tour: architecture, design decisions, and the engineering philosophy behind Luminary.
- **[docs/roadmap.md](docs/roadmap.md)** — what is built, what is open, and what was deliberately abandoned. Check it before proposing work.
- **[docs/architecture.md](docs/architecture.md)** and **[docs/invariants.md](docs/invariants.md)** — the rules a change has to satisfy.

Every other file in `docs/` describes something that already exists; `roadmap.md` is the only one that carries status.

### Contributing

Contributions are welcome. See **[CONTRIBUTING.md](CONTRIBUTING.md)** for the full setup, architecture rules, and PR workflow. In short:

- Fork, branch from `master`, and run `make ci` before opening a PR
- Follow the 6-layer import rule; route all LLM calls through LiteLLM; new endpoints need a pytest test

Found a bug or have an idea? **[Open an issue](https://github.com/nupsea/luminary/issues/new/choose)** — or browse [open issues](https://github.com/nupsea/luminary/issues) to pick something up.

---

## License

Apache 2.0
