# Luminary

 **Read. Ask. Write. Master what matters.**
> A local-first study workspace built on your own documents, that measures what you actually know.

[![Release](https://img.shields.io/github/v/release/nupsea/luminary?label=release)](https://github.com/nupsea/luminary/releases/latest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-Apple%20Silicon-black?logo=apple)](#install)
[![Runs offline](https://img.shields.io/badge/runs-offline-success)](#it-keeps-working-with-the-wifi-off)

 Point it at a book, paper, video or article. Ask it questions and get answers that cite the passage, write down what you understand, turn what matters into flashcards, and let it schedule the review. Nothing ever leaves your machine unless you hand it an API key.

<p align="center">
  <img src="assets/images/luminary.gif" alt="A quick journey in luminary" width="900">
</p>

<p align="center"><a href="https://youtu.be/semZlbJde_Q"><b>Watch the two-minute tour</b></a></p>

---

## Why this and not a chatbot

Three things, and they are the whole point.

**Every answer shows its receipts.** A citation names the section and page it
came from, and the quote is lifted from that passage rather than written by the
model. It is not a nicety — a model asked to retype a quote will happily invent
one, so Luminary never lets it: the model points at a passage, and the passage
speaks for itself.

**A flashcard is checked against your document.** Cards that quote a source get
that quote verified against the text. A card that could not be checked says so
instead of quietly passing. You always know which of your deck is grounded and
which is the model's word for it.

**It measures what you actually remember.** Before you flip a card, you say
whether you know it. Luminary tracks how often you were right, so you find out
where you are confidently wrong — the thing that ordinary review hides. FSRS
schedules the next visit.

---

## Install

**macOS (Apple Silicon)** — download the `.dmg` from the
**[latest release](https://github.com/nupsea/luminary/releases/latest)**, open
it, drag Luminary to Applications. Done.

Nothing else to install: Python, every dependency and the local inference server
ship inside the app. No terminal, Homebrew, Node or separate Ollama. Needs
macOS 14 (Sonoma) or newer.

> The download is ~700 MB. First launch fetches ~1.4 GB of models; your library
> opens in about 20 seconds and the rest finishes in the background. A chat model
> is a separate ~2 GB download the app offers when you first need one, and
> **Speech to text** — which powers audio ingest and voice dictation — is another
> the app fetches on request, because it carries GPL code Luminary may not ship.

On Linux, Windows, or want it as a background service?
**[Every other install path is below.](#other-ways-to-install)**

### What Luminary needs

Luminary runs a model on your machine, so it checks that your machine can
actually do that — and tells you plainly when it cannot, instead of letting you
find out over two minutes of waiting.

| | |
|---|---|
| **Supported** | Apple Silicon Mac · Linux or Windows with an NVIDIA or AMD GPU · a container **with a GPU passed through** (Linux + NVIDIA Container Toolkit, or WSL2), with at least 16 GB of memory |
| **Not supported** | **Intel Mac** · Docker on any Mac, where no GPU passes through and none ever will · any host with no accelerator · under the 16 GB floor |

The check is for the accelerator, never for Docker: a container with a GPU is a
first-class host, and a bare-metal box without one is not.

On an unsupported system Luminary opens your library and **refuses to run a local
model**, rather than taking two minutes to answer. Reading, search, notes,
highlights and your whole learner record are unaffected. Add an API key and
answers and flashcards work normally, because only synthesis is routed — though
ingest enrichment (auto summaries, tags and titles) stays local by design, so it
stays off. **A hosted version, where none of this is your machine's problem, is
the plan for after 1.0.0.**

**Docker with a GPU** is the one supported container setup. The base compose
stack reserves no device, so it is CPU-only and gets refused:

```bash
make docker-run-gpu      # needs the NVIDIA Container Toolkit on the host
```

**To override the check** on a host you know is fine — a large CPU-only server,
or Ollama running outside the container — set `LUMINARY_HOST_SUPPORTED=1`. It
skips every refusal, including the Intel Mac one. Nothing gets faster; you have
only said that you know.

---

## Your first five minutes

1. **Add something.** Library → Add Content. A PDF, EPUB, docx or audio file — or
   paste a web article or YouTube URL.
2. **Wait for the summary card.** Usually under a minute. That means it is
   indexed and ready.
3. **Ask it something.** Open the document and ask in the panel beside it —
   the answer arrives without leaving the page, and clicking a citation marks
   the passage it came from where it stands. `⌘K` searches everything from
   anywhere.
4. **Make some cards.** Study → generate from the document, then Start Review.
   Predict before you flip.

That is the loop. Everything else is built on it.

---

## It keeps working with the wifi off

Luminary's default is a local model through Ollama, so the whole loop — reading,
asking, generating cards, reviewing — runs with no connection and no account.
Turn the wifi off mid-session and it keeps answering.

---

## Faster answers, if you want them

A local model is private and slow. Hand Luminary an API key and synthesis moves
to a hosted model. **Only the question and the passages retrieved for it leave**
— never the document, the library, or your learner record.

Both arms measured back to back on this project's development Mac, one document,
same question, five runs each. Your machine is not that machine, so read these as
a shape rather than a promise — and the receipt under your own first answer is
the figure that actually applies to you:

| | Local (`qwen3.5:4b`) | Hosted |
|---|---|---|
| First token | ~3.1s | ~2.3s |
| Finished answer | 14-37s | 6-11s |

**What you are buying is the finish, not the start.** Both arms search your
library on your machine, and that search is most of the wait before the first
word appears — so first-token time barely moves. It is the whole answer that
arrives two to three times sooner.

**Turning it on**

1. Create a key at [Anthropic](https://console.anthropic.com/settings/keys),
   [OpenAI](https://platform.openai.com/api-keys) or
   [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Luminary asks where answers should come from on first run. If your library
   is older than that question, the Hub offers it once; either way it is
   **Settings -> LLM Mode**.
3. Choose **Answer with your API key**, pick the provider, paste the key, and
   ask something. The line under the answer names the model, the cost, and how
   many passages were sent.

**Where the key is stored** depends on whether the machine has an OS keyring,
and the key panel tells you which case you are in before you paste anything:

| | |
|---|---|
| **macOS app, macOS one-command, Windows native, Linux desktop** | The OS keychain. Never in the library, never in the database |
| **Docker (including Intel Mac and Windows Docker), headless Linux** | There is no keyring, so a key saved in Settings is written to the library database in plain text. Pass it in `.env` beside the compose file instead — see [Running under Docker](#running-under-docker) |

**What never leaves, in any mode:** your library and its index, search and
reranking, transcription, entity extraction, figure reading, and the whole
learner record. Ingest enrichment stays local too, so building a library never
spends your quota. **Settings -> Where your work runs** lists every unit of work with
the model that serves it and whether it is on this machine. **Private mode sends
nothing at all**, and will not even offer you a cloud model.

---

## What else is in it

| | |
|---|---|
| **Read** | Side-by-side PDF viewer, section navigation, dark-page mode, saved reading position, four-colour highlights |
| **Ingest** | PDF, EPUB, docx, Markdown, txt, audio, video, web articles, YouTube, Kindle highlights |
| **Ask** | Hybrid retrieval (vector + keyword + graph), Socratic mode, teach-back, optional web augmentation |
| **Study** | Regular, cloze and code-trace cards; FSRS scheduling; three-phase sessions; prediction calibration |
| **Notes** | Markdown editor with live preview, wiki-links, backlinks, Mermaid and Excalidraw |
| **Dictate** | Speak instead of typing — into a note, a teach-back answer or a question. Transcribed on your machine by Whisper; nothing is uploaded |
| **Track** | Mastery rings per document, "what's about to slip", study activity, time on task |
| **Figures** | Diagrams and charts pulled out of PDFs and described by a vision model, so an answer can draw on them |
| **Export** | Markdown vault (Obsidian-compatible), Anki `.apkg`, flashcard CSV |

The Hub is the daily entry point: it picks the one thing most worth doing now —
review what is due, carry on reading, or write something down.

Figure descriptions are the one genuinely expensive part of ingest — one vision
call per figure — so on a CPU-only host a heavily illustrated PDF takes a while
to finish enriching. The document is readable and searchable before that
finishes, and `PDF_VECTOR_FIGURES=false` turns the fallback off.

---

## Other ways to install

<details>
<summary><b>macOS — one command (background service + CLI)</b></summary>

Choose this if you want Luminary running at login with a command-line tool, or
you already have a `~/.luminary` library from a source install.

The two macOS installs are independent — separate libraries, neither reads the
other's — so pick one rather than running both.

> **Beta.** Not yet tested across a wide range of Macs. If it fails, use the
> source install and please [open an issue](https://github.com/nupsea/luminary/issues).
> It registers a background service, and `luminary uninstall` cleanly reverses it.

```bash
curl -fsSL https://raw.githubusercontent.com/nupsea/luminary/master/scripts/bootstrap.sh | bash
```

Starts Luminary at login and opens it in your browser. No Homebrew, Node, git or
Xcode tools required. The app installs to
`~/Library/Application Support/Luminary`; your library stays at `~/.luminary`, so
upgrades never touch your data. Needs macOS 14+. First install pulls ~5 GB of
models and takes 15–25 minutes.

```bash
luminary status      # version, paths, service and Ollama state
luminary stop        # stop the background service
luminary update      # upgrade in place; your library is preserved
luminary uninstall   # remove the app; asks before touching your library
```
</details>

<details>
<summary><b>Linux & WSL — from source</b></summary>

A stock Ubuntu image ships none of `git`, `make` or `curl`, so install those first:

```bash
sudo apt-get update && sudo apt-get install -y git make curl
git clone https://github.com/nupsea/luminary.git
cd luminary
make install   # Installs uv, Node, Ollama; pulls models; builds the app
make start     # Production server on http://localhost:7820
```

`make install` needs `sudo` once, for Ollama and the `zstd` its installer
requires. Node is fetched into `~/.local` — apt only carries Node 18 and the
build needs 20+. Verified end to end on a clean `ubuntu:24.04` container (arm64).

Audio and video ingestion and voice dictation are not part of it: add **Speech
to text** from Settings, and `ffmpeg` from apt for video.
</details>

<details>
<summary><b>Windows — native (recommended), or Docker</b></summary>

**Use the native install.** It installs Ollama for Windows, which uses your GPU
(CUDA on NVIDIA, ROCm on AMD) with no configuration. The Docker image cannot:
the compose stack reserves no GPU device, so inference there is **CPU-only on
every machine**.

In a normal PowerShell window (no admin):

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; .\scripts\install.ps1   # one-time; creates start.ps1
.\start.ps1                                                              # each time after
```

Open http://localhost:7820 when the log settles. The native install covers everything except audio and video. For those, install
ffmpeg and leave it on `PATH` (`winget install Gyan.FFmpeg`), then add **Speech
to text** from Settings — Luminary fetches that one itself. Voice dictation
needs that same component and no ffmpeg; the mic button appears once it is in.

**Docker, only if something blocks the native install** and you have an NVIDIA
GPU — without one Luminary refuses to run a local model. See
[Running under Docker](#running-under-docker).

```powershell
$env:WITH_MEDIA=1    # optional: audio, video and YouTube ingest
make docker-run-gpu
```
</details>

<details>
<summary><b>macOS (Intel / x86_64) — not supported</b></summary>

**Intel Macs cannot run Luminary well, and it no longer pretends otherwise.**

There is no native install: `lancedb` publishes no macOS x86_64 wheel, and
neither does `torch` past 2.2.2, so `make install` and `bootstrap.sh` both refuse
before they start. Docker was the remaining route and it leads somewhere worse.
Docker Desktop on macOS is a Linux VM under Apple's Virtualization.framework,
and **neither Metal nor the Neural Engine is exposed to it** — on any Mac,
Intel or Apple Silicon. There is no setting that fixes this. Measured on an
i7-8850H: `qwen3.5:4b` at ~6 tok/s, ~121s for one question, ~143s to enrich a
128-page book.

Luminary now checks the machine rather than the installer, and says so plainly
rather than letting you discover it over two minutes of waiting.

**What still works.** Reading, search, notes, highlights, the graph and your
whole learner record are unaffected — none of them needs a fast model. Add an
OpenAI, Anthropic or Google key in Settings and answers and flashcards work
properly too, because only synthesis is routed; see
[Faster answers, if you want them](#faster-answers-if-you-want-them).

**What is coming.** A hosted version of Luminary, where none of this is your
machine's problem. That is the plan for after 1.0.0.
</details>

> First launch is slow because it downloads ML models. Every launcher polls the
> server and prints `Luminary is ready` only when it is. Background `Warmup:` log
> lines after that are normal.

## Updating

**Your library is never touched by an update.** It lives at `~/.luminary` (or
`~/Library/Application Support/sh.luminary.app` for the bundled app), outside
whatever the update replaces. Schema changes are applied by migrations when the
server next boots.

| How you installed | How you update |
|---|---|
| One-command script (`bootstrap.sh`) | `luminary update` — re-runs the installer against the latest release |
| DMG | Download the new DMG and replace the app |
| From source | `git pull && make install` — `install.sh` is idempotent |
| Docker | `git pull && make docker-run-gpu` — it passes `--build`, so this rebuilds |

`luminary update` resolves the newest **published release**, not `master`, and
verifies the download against the release's `.sha256` before replacing anything.
It stages the download and swaps it in, so an interrupted update cannot leave a
half-replaced install behind. Pin a specific version with
`LUMINARY_VERSION=0.8.24`.

Under Docker, `make docker-run-gpu` already passes `--build`, so it rebuilds the
image and recreates the containers in one step — `make docker-build` is only for
building without starting. Neither stop target passes `--volumes`, so your
library survives `make docker-down`.

## Running it on real hardware

Everything below is reference. Skip it unless something feels slow or the app
warns you about memory — the defaults are sized for the machine you are on.

**On a Mac under Docker, expect ingestion to be slow.** No GPU passes through;
run the model outside the container instead. The Docker section has both ways.

<details>
<summary><b>How much memory it actually needs</b></summary>

Measured, not estimated — every figure below was read off a running instance.

| what is resident | GB |
|---|---|
| Ollama serving `qwen3.5:4b` — chat *and* figures | 3.2 |
| Backend at rest: embedder 0.5, reranker 0.3, entity model 1.4 | 2.4 |
| Peak while a document is ingesting | +0.8 |
| **total while ingesting** | **6.4** |

**16 GB is the supported floor**, and the default configuration uses 40% of it —
one model reads figures and answers questions, so nothing is evicted to do either.

Luminary will not spend the rest on a second model. A resident set is budgeted at
half the machine, so pointing **Settings → Vision** at the dedicated 6.8 GB reader
on a 16 GB machine is declined with a reason rather than accepted into swap: the
pair is 10.0 GB against an 8 GB budget. From 24 GB up it is accepted. The limit is
deliberate — a desktop app that swaps degrades every other window on the machine,
not just its own.

A smaller machine still starts and is told it is under the floor, rather than
being quietly narrowed.

Answering questions afterwards sits lower still: the entity model is released
after 180 seconds idle, returning 1.4 GB, and only ingestion and the reindex
script ever need it back.

Model sizes are Ollama's own `/api/ps` figures at the deployed context window.
A process RSS is not comparable — on unified memory it double-counts weights the
runner maps — so `scripts/model_footprint.py` is what these come from.
</details>

### Running under Docker

**Docker is supported only when the model gets a GPU.** Without one Luminary
refuses to run a local model rather than take minutes to answer — see
[What Luminary needs](#what-luminary-needs). Docker on macOS never qualifies: no
GPU passes through Apple's VM, on Intel or Apple Silicon.

**Prerequisites**

- Docker Desktop or Docker Engine, with `docker compose` v2 (not a pre-release)
  and **buildx 0.17.0+**. Both ship in Docker Desktop; a stale toolchain is
  refused up front rather than hanging mid-build.
- **10 GB free disk** before the first build: a 3.4 GB image (4.2 with
  `WITH_MEDIA=1`) plus a 3.4 GB model blob.
- **16 GB of memory for the container.** Docker Desktop gives its VM a fraction
  of the host, often half, so a 16 GB Mac presents as ~7.7 GB and is refused.
  Raise it in **Settings → Resources → Memory**.
- For `docker-run-gpu`: the **NVIDIA Container Toolkit** on the host.

**Commands**

```bash
make docker-run-gpu           # model in a container with an NVIDIA GPU
make docker-run-host-ollama   # model on the host, app in a container
make docker-stop              # stop, keep containers for a fast restart
make docker-down              # also remove containers and the network
```

`WITH_MEDIA=1` adds audio, video and YouTube ingest (GPL components, opt-in).
Neither stop target touches your library — no target here ever passes
`--volumes`.

**Worth knowing**

- **Secrets.** A container has no OS keyring, so an API key saved in Settings
  goes into the library database as plain text. Put it in `.env` beside the
  compose file instead.
- **Reclaiming disk.** `docker builder prune -af` and `docker image prune -af`.
  **Never add `--volumes`** — that deletes `luminary-data`, which is your library.
- **Why the GPU rule exists.** Measured on an Intel i7-8850H in a 12 GB Docker
  VM: `qwen3.5:4b` loaded in 9.6–155s, one question took 261s of which 87.5s was
  the model load, and vision calls ran 278–305s each.


<details>
<summary><b>Why the first question after a break is slow, and what is already done about it</b></summary>

On a host without GPU acceleration, loading the model is the single largest
thing a question can wait on. Measured on an Intel i7-8850H in a 12 GB Docker
VM, `qwen3.5:4b` loads in anywhere from 9.6 s to 155 s; one question took 261 s
end to end and 86 s of that was the load, because Ollama had evicted the model
during the previous half-hour of idleness.

Luminary handles this without configuration: start-up times how long this
machine takes to produce one trivial answer, and where that says local
inference is expensive the backend pings the model inside the keep-alive window
so it is never evicted. A host that loads quickly
is left alone entirely — no pings, no pinned memory.

To take the eviction off the table yourself, keep the model resident for good:

```sh
OLLAMA_KEEP_ALIVE=-1 make docker-run-gpu
```

That pins the model's memory (3.4 GB for `qwen3.5:4b`) for as long as Ollama
runs, which is worth it on a machine where a load costs a minute and wasteful
on one where it costs three seconds.

The other thing a question can wait behind is the chat's own suggested
questions, which are generated by the same model and, on the same host, took
67 s. When a question arrives while they are still being written, they are
abandoned and the ready-made suggestions are shown instead — the question gets
the machine. Where suggestions are quick they finish first and nothing is
abandoned.

**Two runtime bounds ship set.** Ollama's own defaults are not sized for a
laptop: the model stays resident for 30 minutes rather than Ollama's 5, and
llama.cpp's prompt cache is capped at 512 MB rather than its default 8192 MB —
which is more than a default Docker VM has in total. Override either with
`OLLAMA_KEEP_ALIVE` and `LLAMA_ARG_CACHE_RAM`. On a native macOS or Linux
install the Ollama server is yours, not ours, so set them there (`launchctl
setenv`, or your systemd unit) if you want them changed.
</details>

## Choosing a model

<details>
<summary><b>Which model runs, and how to change it</b></summary>

If Ollama is not running or no model is pulled, only the LLM features (chat,
teach-back, flashcards) pause — reading, search and review keep working. Fix it
with `ollama serve` and `ollama pull qwen3.5:4b` (under Docker the `--profile ai`
sidecar does it on first start).

Luminary sizes its models from your machine's RAM, and `make install` pulls what
that band needs.

| RAM | Profile | Text (chat, generation, background) | Figures | Resident |
|-----|---------|-------------------------------------|---------|----------|
| under 16 GB | `low` | `qwen3.5:4b` | the same model | 3.2 GB |
| 16–24 GB | `standard` | `qwen3.5:4b` | the same model | 3.2 GB |
| over 24 GB | `performance` | `qwen2.5:14b-instruct` | `qwen3.5:4b` | 12.9 GB |

`qwen3.5:4b` reads images as well as text, which is what lets one model fill
every role on a small machine. A second model is loaded only where both fit at
once — a 16 GB laptop can keep one model loaded, so the larger profile buys
concurrency rather than a second model.

Any Ollama-served model works; these are the ones with measured footprints and
eval numbers behind them. `ollama show <model>` lists whether a model reads images.

| Model | Command | Best for | Resident |
|-------|---------|----------|----------|
| Qwen 3.5 4B (default) | `ollama pull qwen3.5:4b` | Everyday use; also reads figures | 3.2 GB |
| Llama 3.2 3B | `ollama pull llama3.2` | The lightest option, text only | 2.9 GB |
| Phi-4 mini | `ollama pull phi4-mini` | Text only | 3.5 GB |
| Gemma 3 4B | `ollama pull gemma3:4b` | Reads figures, but least accurate on them | 3.6 GB |
| Qwen 2.5 14B | `ollama pull qwen2.5:14b-instruct` | Highest quality text, needs 24 GB+ | 9.7 GB |
| Qwen 2.5 VL 7B | `ollama pull qwen2.5vl:7b` | A dedicated figure reader | 6.8 GB |

**`backend/.env` is the one file to edit** — copy `backend/.env.example`, which
documents every model knob. Nothing else reads a model name out of
configuration, so a change there reaches every call site.

Three layers decide which model runs, strongest first:

1. **Settings in the app** — stored per-machine, wins over the file.
2. **`backend/.env`** — the deployment default for this install.
3. **The registry default** — sized from your RAM, as above.

```bash
LITELLM_DEFAULT_MODEL=ollama/gemma3:4b   # chat, and the fallback for everything
LITELLM_GENERATION_MODEL=                # empty = follow the above
VISION_MODEL=ollama/qwen2.5vl:7b         # must be a model with vision
```

Run `make models` to print what your configuration costs, which roles resolve to
which model, and any warnings.

**Cloud models.** An id is `provider/name`. A local model needs no key; a hosted
one does. You can also add the key in Settings.

A native install puts that key in your OS keychain. A container has none, so
Docker installs store it in the database as plain text — pass it as an
environment variable instead (see [Running under Docker](#running-under-docker)).

```bash
LITELLM_DEFAULT_MODEL=openai/gpt-4o
OPENAI_API_KEY=sk-...

ANTHROPIC_API_KEY=sk-ant-...
LITELLM_DEFAULT_MODEL=anthropic/claude-3-7-sonnet-latest

LITELLM_DEFAULT_MODEL=gemini/gemini-2.5-pro
GOOGLE_API_KEY=...
```

**If you pick a model too big for the machine,** Luminary warns and carries on —
at startup, at `GET /settings/models`, and in `make models`. It never overrides
your choice. The warning is real: a model that does not fit swaps under load, and
the first symptom is usually a stall during ingestion rather than an error.
</details>

<details>
<summary><b>Configuration reference</b></summary>

All settings are environment variables in `backend/.env` (gitignored).
`backend/.env.example` is the annotated template.

| Variable | Default | Description |
|----------|---------|-------------|
| `LITELLM_DEFAULT_MODEL` | `ollama/qwen3.5:4b` | Chat, and the fallback for every other role |
| `LITELLM_GENERATION_MODEL` | *(empty)* | Flashcards and summaries; empty follows the model above |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama server address |
| `VISION_MODEL` | `ollama/qwen3.5:4b` | Image and figure analysis; must be a model with vision |
| `FLASHCARD_FACTUALITY_MODEL` | *(empty)* | Checks a generated card's answer against its passage; off by default |
| `LUMINARY_MEMORY_PROFILE` | *(from RAM)* | `standard` / `performance`; overrides what host RAM would choose. `low` and `public` are read as `standard` so an older `.env` keeps working |
| `PDF_VECTOR_FIGURES` | `true` | Rasterize vector-drawn PDF figures (LaTeX papers embed no images) |
| `LUMINARY_MODE` | `full` | `full` = every feature; `public` = curated learner surfaces, SPA + API on one port |
| `GLINER_ENABLED` | `true` | Entity extraction (disable on <8 GB RAM) |
| `DATA_DIR` | `.luminary` | Where databases and embeddings live |
</details>

---

## Your data

Everything — library database, vector embeddings, knowledge graph, notes — lives
in one folder. The bundled app keeps it in
`~/Library/Application Support/sh.luminary.app/`; a source install uses
`.luminary/` at the project root.

Upgrading keeps your library, flashcards and review history. The schema is
versioned with Alembic and the server migrates on startup — you never delete the
database to take a new version.

To move machines, copy `.luminary/`, `DATA/` (source files) and `backend/.env`.

To remove the app, drag it to the Trash. That leaves your library alone; delete
the folder above if you want that gone too.

<details>
<summary><b>Re-extracting figures from a document already in your library</b></summary>

Extraction improvements only apply to documents ingested after them. To re-run
figure extraction without re-uploading:

```bash
curl -X POST http://localhost:7820/documents/<document_id>/images/reextract
```

Extraction deduplicates on content hash, so this only adds figures the previous
run missed. `GET /documents/<document_id>/enrichment` shows progress.
</details>

---

## For contributors

<details>
<summary><b>Architecture, commands and the eval harness</b></summary>

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
  repos/          Database reads and writes
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

| Command | What it does |
|---------|-------------|
| `make install` | One-time setup (uv, Node, Ollama, models, build) |
| `make start` | Public-mode server on :7820 |
| `make luminary` | Backend + frontend in full mode (:7820 + :5173) |
| `make dev` | Backend with `--reload` + frontend dev server, for editing code |
| `make stop` | Stop Luminary on :7820, gracefully (also stops the container when it serves the port) |
| `make clean` | Free :7820, :5173 and :5174 — listeners only, SIGTERM first |
| `make logs` | Backend + frontend with colorized, prefixed output in one terminal |
| `make test` | Backend unit + integration tests |
| `make lint` | Ruff + tsc + eslint + manifest checks |
| `make ci` | **The gate.** Lint, layer check, tests, build, tsc, eslint, vitest |
| `make smoke` | ~180 HTTP contract scripts against a running backend |
| `make eval` | Retrieval quality against committed floors; needs a running backend |
| `make db-migrate` | Apply pending migrations (the server also does this on boot) |
| `make db-revision m="..."` | Generate a migration after changing `models.py` |
| `make docker-build` | Build the image (`WITH_MEDIA=1` adds ffmpeg and the transcriber) |
| `make docker-run-gpu` | Run via Docker Compose, model on an NVIDIA GPU |
| `make docker-stop` | Stop the compose stack, containers kept for a fast restart |
| `make docker-down` | Stop and remove containers and network; **volumes, i.e. your library, are kept** |

**Evaluation harness.** Retrieval is scored with HR@5 / MRR / nDCG@10;
faithfulness uses a dedicated NLI model (Vectara HHEM-2.1-Open) rather than an
LLM judge, so it is deterministic and needs no API key. See
[`evals/README.md`](evals/README.md).

```bash
cd evals && uv run python run_eval.py --dataset book --backend-url http://localhost:7820
```

Asserted thresholds: HR@5 ≥ 0.50, MRR ≥ 0.35, and — whenever a run generated
answers — faithfulness ≥ 0.30, answer rate ≥ 0.75 and citation coverage ≥ 0.60.
The `notes` dataset holds a higher bar (HR@5 ≥ 0.60, MRR ≥ 0.45); `paper` holds
0.80 / 0.60. nDCG@10 is computed and reported but **never asserted** — most
goldens carry single-passage relevance, where nDCG degrades to a log-discounted
single-hit metric. These are **collapse detectors, not quality bars** — clearing
them says a leg of the funnel is alive, not that a change was an improvement. A
metric that was requested and could not be computed fails the run rather than
being skipped.

**Platform support.**

| Platform | Status |
|---------|--------|
| macOS Apple Silicon | Native, fully supported |
| macOS Intel | Docker required for backend; a hosted model is recommended for generation (no GPU, ~6 tok/s locally) |
| Linux / WSL | Native, same steps |
| Windows | Docker, or natively via `scripts/install.ps1` |

**Documentation.**

- **[DEEP_DIVE.md](DEEP_DIVE.md)** — architecture, design decisions, and the
  engineering philosophy.
- **[docs/roadmap.md](docs/roadmap.md)** — what is built, what is open, what was
  deliberately abandoned. Check it before proposing work.
- **[docs/architecture.md](docs/architecture.md)** and
  **[docs/invariants.md](docs/invariants.md)** — the rules a change has to satisfy.

Every other file in `docs/` describes something that already exists;
`roadmap.md` is the only one carrying status.
</details>

**Contributions are welcome.** See **[CONTRIBUTING.md](CONTRIBUTING.md)**. In
short: fork, branch from `master`, run `make ci` before opening a PR, follow the
6-layer import rule, route all LLM calls through LiteLLM, and give new endpoints
a pytest test.

Found a bug or have an idea?
**[Open an issue](https://github.com/nupsea/luminary/issues/new/choose)** — or
browse [open issues](https://github.com/nupsea/luminary/issues) to pick something up.

**If the app will not start,** the startup screen says what went wrong and can
open a pre-filled bug report — nothing is sent until you have read and submitted
it yourself. There is also a log at `~/Library/Logs/Luminary/luminary.log`.

---

## License

Apache 2.0
