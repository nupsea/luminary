# Luminary

**Study smarter, locally.** Upload a book or paper, ask questions with source citations, and review with FSRS-scheduled flashcards — your data never leaves your machine.

> Local-first document learning with cited Q&A and science-backed spaced repetition.

No subscription. No cloud sync. Works offline with a local LLM (Ollama) or any API key you supply.

---

## Install and run (one command)

```bash
git clone https://github.com/nupsea/luminary.git
cd luminary
make install   # installs uv, Node, Ollama; pulls default models; builds the app
make start     # starts the prod server on http://localhost:7820
```

`make install` is idempotent — safe to run again when you update. It handles Ollama, model pulls, Python deps, and frontend build automatically.

> **macOS Intel?** Docker is required for the backend. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) first, then `make docker-build && make docker-run`.

Open **http://localhost:7820** when the terminal shows a ready banner.

---

## Your first 5 minutes

1. **Upload a document** — Learning tab → Upload → select a PDF or text file
2. **Wait for processing** — a summary card appears when indexing finishes (usually under a minute)
3. **Ask a question** — Chat tab → ask anything about your document; citations link back to the source section
4. **Review flashcards** — Study tab → Start Review → grade cards; Luminary schedules the next review using FSRS

That's the core loop. Luminary adds more as you return: mastery rings on the library card, a "What's about to slip" widget, reading continuity ("Continue reading" picks up exactly where you left off), and a prediction-calibration graph on Progress.

---

## Features

### Cited Q&A — Ask across your library

Chat with every document you've uploaded. Every answer includes citations with section heading, excerpt, and page number.

Press **⌘K** from any tab to open the Quick Ask panel. Toggle **Socratic mode** (default) to get a probing question before the answer — useful for active recall.

### Spaced repetition — Remember what you read

AI-generated flashcards (regular, cloze-deletion, code-trace) scheduled by the FSRS algorithm. Review sessions are shaped into three phases:

- **Warm-up** — well-retained cards to build momentum
- **Engage** — cards that need work
- **Reflect** — phase label on the last 15%

Before flipping a card, predict your confidence (Know it / Unsure / Blank). Luminary tracks your prediction accuracy on the Progress tab.

### Local-first reader — Read and annotate

Side-by-side PDF viewer with section navigation. Luminary saves your reading position; "Continue reading" brings you back to the right section. Generate flashcards from a text selection in the reader.

### Notes — Write alongside reading

Markdown editor with live preview. Notes are indexed and appear in search. Supports Mermaid diagrams and Excalidraw sketches.

### Progress — See what's sticking

- Mastery rings on every document card (weighted FSRS stability)
- "What's about to slip" widget (cards approaching the forgetting threshold)
- Study activity chart (last 30 days)
- Prediction calibration graph (are your confidence ratings accurate?)
- Sort library by "Weakest first" to target the documents that need the most work

---

## Models

Luminary defaults to **Gemma 4** via Ollama (pulled by `make install`).

| Model | Command | Best for | VRAM |
|-------|---------|----------|------|
| Gemma 4 E4B (default) | `ollama pull gemma4` | Everyday use, laptops | ~4 GB |
| Gemma 4 26B A4B | `ollama pull gemma4:26b-a4b` | Balanced quality/speed | ~16 GB |
| Gemma 4 31B | `ollama pull gemma4:31b` | Maximum quality | ~20 GB |
| Llama 3.1 8B | `ollama pull llama3.1` | Lightweight alternative | ~5 GB |

### Switch to a cloud model (optional)

Create `backend/.env`:

```bash
# OpenAI
LITELLM_DEFAULT_MODEL=openai/gpt-4o
OPENAI_API_KEY=sk-...

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
LITELLM_DEFAULT_MODEL=anthropic/claude-sonnet-4-20250514

# Google
LITELLM_DEFAULT_MODEL=gemini/gemini-2.5-flash
GOOGLE_API_KEY=...
```

---

## Configuration

All settings are environment variables in `backend/.env` (gitignored).

| Variable | Default | Description |
|----------|---------|-------------|
| `LITELLM_DEFAULT_MODEL` | `ollama/gemma4` | LLM for chat, summaries, flashcards |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server address |
| `VISION_MODEL` | `ollama/llava:7b` | Model for image/figure analysis |
| `GLINER_ENABLED` | `true` | Entity extraction (disable on <8 GB RAM) |
| `DATA_DIR` | `.luminary` | Where databases and embeddings live |

---

## Your data

Everything — library database, vector embeddings, knowledge graph, notes — is in `.luminary/` at the project root. To move to a new machine: copy `.luminary/`, `DATA/` (source files), and `backend/.env`.

Export options: Markdown vault (Obsidian-compatible), Anki deck (`.apkg`), flashcard CSV.

---

## Make commands

| Command | What it does |
|---------|-------------|
| `make install` | One-time setup (uv, Node, Ollama, models, build) |
| `make start` | Start the prod server on :7820 |
| `make luminary` | Start backend + frontend in dev mode (:7820 + :5173) |
| `make stop` | Stop all Luminary processes |
| `make test` | Unit + integration tests |
| `make lint` | Ruff + tsc |
| `make ci` | Full CI: deps, lint, layer check, tests, build |
| `make docker-build` | Build the Docker image |
| `make docker-run` | Run via Docker Compose (with Ollama sidecar) |

---

## Evaluation harness

Luminary ships a RAGAS-based retrieval eval harness with golden Q&A datasets. See [`evals/README.md`](evals/README.md) for the full picture.

```bash
cd evals && uv run python run_eval.py --dataset book --backend-url http://localhost:7820
```

Thresholds: HR@5 ≥ 0.60, MRR ≥ 0.45, Faithfulness ≥ 0.65.

---

## Platform notes

| Platform | Status |
|---------|--------|
| macOS Apple Silicon | Native, fully supported |
| macOS Intel | Docker required for backend (auto-detected by `make luminary`) |
| Linux / WSL | Native, same steps |

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
| ML | BAAI/bge-m3 embeddings (ONNX), GLiNER (zero-shot NER) |
| Retrieval | RRF hybrid: vector + BM25 + graph traversal |
| Spaced rep | FSRS algorithm |
| Frontend | React 18, TypeScript 5, Vite, shadcn/ui, Tailwind CSS |
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

### Contributing

1. Fork and create a feature branch
2. `cd backend && uv sync` / `cd frontend && npm install`
3. `make ci` must pass before opening a PR
4. Follow the 6-layer import rule (no reverse imports)
5. All LLM calls go through LiteLLM
6. New endpoints require at least one pytest test

---

## License

MIT
