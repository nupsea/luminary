# Installing and running Luminary

The one-click installs are in the [README](../README.md#install). This page covers every other
way to run Luminary, and the reference for sizing, models and configuration.

## Other ways to install

### macOS — background service and CLI

For Luminary running at login with a `luminary` command, or for an existing `~/.luminary` library
from a source install. It and the DMG keep separate libraries, so pick one.

```bash
curl -fsSL https://raw.githubusercontent.com/nupsea/luminary/master/scripts/bootstrap.sh | bash
```

Installs to `~/Library/Application Support/Luminary`; the library stays at `~/.luminary`. Needs
macOS 14+. The first install pulls ~5 GB of models and takes 15–25 minutes.

```bash
luminary status      # version, paths, service and Ollama state
luminary stop        # stop the background service
luminary update      # upgrade in place; the library is kept
luminary uninstall   # remove the app; asks before touching the library
```

### Linux and WSL — from source

A stock Ubuntu image has none of `git`, `make` or `curl`:

```bash
sudo apt-get update && sudo apt-get install -y git make curl
git clone https://github.com/nupsea/luminary.git && cd luminary
make install   # uv, Node, Ollama, models, build; needs sudo once for Ollama
make start     # http://localhost:7820
```

Node is fetched into `~/.local` because apt carries Node 18 and the build needs 20+. Audio, video
and dictation need **Speech to text** from Settings, and `ffmpeg` from apt for video.

### Windows — from source

In a normal PowerShell window (no admin):

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; .\scripts\install.ps1   # once; creates start.ps1
.\start.ps1                                                              # each time after
```

Open http://localhost:7820 when the log settles. For audio and video, install ffmpeg on `PATH`
(`winget install Gyan.FFmpeg`) and add **Speech to text** from Settings.

### Intel Macs — not supported

`lancedb` publishes no macOS x86_64 wheel and `torch` none past 2.2.2, so the native installs
refuse. Docker on any Mac exposes neither Metal nor the Neural Engine: measured on an i7-8850H,
`qwen3.5:4b` ran at ~6 tok/s and took ~121s per question. Reading, search, notes and the learner
record still work, and an API key makes answers and flashcards work too.

## Running under Docker

Docker is supported only when the model gets a GPU; the base compose stack reserves no device, so
it is CPU-only and refused. Docker on macOS never qualifies.

Needs Docker with `docker compose` v2 and buildx 0.17.0+, 10 GB free disk (a 3.4 GB image, 4.2
with `WITH_MEDIA=1`, plus a 3.4 GB model), 16 GB of memory given to the container (Docker Desktop
often gives its VM half the host), and the NVIDIA Container Toolkit for `docker-run-gpu`.

```bash
make docker-run-gpu           # model in the container on an NVIDIA GPU
make docker-run-host-ollama   # model on the host, app in a container
make docker-stop              # stop, keep containers
make docker-down              # also remove containers and the network
```

`WITH_MEDIA=1` adds audio, video and YouTube ingest (GPL components, opt-in). No target passes
`--volumes`, and neither should you: the `luminary-data` volume is the library.

A container has no OS keyring, so an API key saved in Settings is stored in the library database
in plain text. Pass it in `.env` beside the compose file instead.

## Memory

Read off a running instance with `scripts/model_footprint.py` (Ollama's `/api/ps`, not process
RSS, which double-counts mapped weights on unified memory):

| Resident | GB |
|---|---|
| Ollama serving `qwen3.5:4b`, chat and figures | 3.2 |
| Backend at rest: embedder 0.5, reranker 0.3, entity model 1.4 | 2.4 |
| Extra while a document ingests | +0.8 |
| **Total while ingesting** | **6.4** |

16 GB is the supported floor. A resident set is budgeted at half the machine, so a second model
(the 6.8 GB figure reader) is declined on 16 GB and accepted from 24 GB. The entity model is
released after 180s idle.

Ollama's defaults are resized for a laptop: the model stays loaded 30 minutes, and the prompt
cache is capped at 512 MB. Override with `OLLAMA_KEEP_ALIVE` and `LLAMA_ARG_CACHE_RAM`
(`OLLAMA_KEEP_ALIVE=-1` keeps the model loaded for good).

## Choosing a model

Off Apple Silicon the text model is `qwen3.5:4b` whatever the RAM; other models are a choice in
Settings. On Apple Silicon it is sized from RAM:

| RAM | Text | Figures | Resident |
|---|---|---|---|
| 16–24 GB | `qwen3.5:4b` | the same model | 3.2 GB |
| over 24 GB | `qwen2.5:14b-instruct` | `qwen3.5:4b` | 12.9 GB |

Models with measured footprints:

| Model | Best for | Resident |
|---|---|---|
| `qwen3.5:4b` (default) | Everyday use; also reads figures | 3.2 GB |
| `llama3.2` | Lightest, text only | 2.9 GB |
| `phi4-mini` | Text only | 3.5 GB |
| `gemma3:4b` | Reads figures, least accurately | 3.6 GB |
| `qwen2.5:14b-instruct` | Best text, needs 24 GB+ | 9.7 GB |
| `qwen2.5vl:7b` | Dedicated figure reader | 6.8 GB |

Which model runs, strongest first: Settings in the app, then `backend/.env`, then the registry
default above. `make models` prints what the configuration resolves to and warns when a model is
too big for the machine; the choice is never overridden.

## Configuration reference

Source and Docker installs read `backend/.env` (gitignored); `backend/.env.example` documents
every key.

| Variable | Default | Description |
|---|---|---|
| `LITELLM_DEFAULT_MODEL` | `ollama/qwen3.5:4b` | Chat, and the fallback for every other role |
| `LITELLM_GENERATION_MODEL` | *(empty)* | Flashcards and summaries; empty follows the above |
| `VISION_MODEL` | `ollama/qwen3.5:4b` | Figure analysis; must read images |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama server |
| `FLASHCARD_FACTUALITY_MODEL` | *(empty)* | Checks a card's answer against its passage; off by default |
| `LUMINARY_MEMORY_PROFILE` | *(from RAM)* | `standard` or `performance` |
| `LUMINARY_HOST_SUPPORTED` | *(unset)* | `1` skips every host refusal, for a host you know is fine |
| `PDF_VECTOR_FIGURES` | `true` | Rasterize vector-drawn PDF figures; each costs a vision call |
| `LUMINARY_MODE` | `full` | `full` = every feature; `public` = learner surfaces, SPA and API on one port |
| `GLINER_ENABLED` | `true` | Entity extraction |
| `DATA_DIR` | `.luminary` | Where the library lives |

Cloud models are `provider/name` ids with the matching key (`OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`), or a key added in Settings.

## Re-extracting figures

Extraction improvements apply only to documents ingested after them. To re-run it for one
document (it deduplicates on content hash, so it only adds what was missed):

```bash
curl -X POST http://localhost:7820/documents/<document_id>/images/reextract
```
