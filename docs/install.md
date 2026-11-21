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

### What a source install changes

`make install` (users) and `make install-dev` (contributors) touch only these:

| Where | What |
|---|---|
| The checkout | `backend/.venv`, `frontend/node_modules`, `frontend/dist`, five keys in `backend/.env` |
| `~/.local/bin`, `~/.local/share/uv`, `~/.cache/uv` | uv and the Python it manages, if uv was missing |
| Homebrew (macOS) or `~/.local/share/luminary/node` (Linux) | Node, if missing or older than `NODE_MIN` in `scripts/install.sh` |
| Homebrew or Ollama's script | Ollama, if missing; then the default model in `~/.ollama` |
| `~/.cache/luminary/test-models` | `install-dev` only: the 1.4 GB of weights the test suite embeds with |

No system Python or global `site-packages` is modified. uv's installer appends one line to your
shell profile so `uv` is on PATH in new terminals; make targets do not depend on it.

`.install-manifest` records which of the global items this checkout installed. `make uninstall`
removes the checkout's items and exactly those, and keeps the dev library `.luminary/`:

```bash
make uninstall ARGS=--dry-run       # list what would go
make uninstall                      # asks first
make uninstall ARGS=--purge-data    # also delete .luminary/ (documents, notes, flashcards)
```

Anything global it finds but has no record of (an install made before the manifest existed, or a
tool that was already there) is kept, and listed at the end with the command to remove it by hand.

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

`install.ps1` installs Python, Node, uv and Ollama only where they are missing, pulls the model,
and sets four user environment variables for Ollama (`OLLAMA_KEEP_ALIVE`, `OLLAMA_NUM_PARALLEL`,
`OLLAMA_MAX_LOADED_MODELS`, `LLAMA_ARG_CACHE_RAM`). It records each in `.install-manifest`,
including a variable's earlier value. `uninstall.ps1` removes exactly those, restores the earlier
values, and keeps `.luminary\`; unrecorded leftovers are listed with the command to remove them:

```powershell
.\scripts\uninstall.ps1 -DryRun      # list what would go
.\scripts\uninstall.ps1              # asks first
.\scripts\uninstall.ps1 -PurgeData   # also delete .luminary\ (documents, notes, flashcards)
```

A user variable changed since the install is kept.

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

### Reaching it from another machine

Compose binds `127.0.0.1`, and the server answers only to loopback names. To serve other machines,
set `LUMINARY_ALLOWED_HOSTS` to the names they will use (`luminary.lan,192.168.1.20`) and publish
the port beyond loopback. Every API request from another machine then needs a paired device's
token, whatever its headers say. Mint a code from inside the container, which is the only place
allowed to:

```bash
docker exec <container> python -m app.scripts.pairing_code
```

The device sends the code to `POST /api/devices/pair` and gets back the token to send as
`Authorization: Bearer <token>`. One address (an IPv6 address by its /64) may make four pairing
attempts in any five minutes. A token reads the library (documents, sections, notes, cards,
study, search and Ask with the server's own model), writes notes and records card reviews, and
nothing else: settings, setup, connectors, the blog, admin, deletes, spaces and devices answer
only to Luminary on the server itself. A reverse proxy on the server (`tailscale serve`, Caddy)
connects from loopback, so with `LUMINARY_ALLOWED_HOSTS` set any request naming another host
or carrying a forwarding header needs a token too. A browser cannot pair yet, so the app's pages are usable only on
the server itself. Publishing the port beyond loopback without the setting leaves it guarded only
by the `Host` header, which any client other than a browser can set to `127.0.0.1`.

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

## Spaces, and moving one to another computer

A space is a whole library of its own (the code and API call it a library). The tile at the top
of the sidebar is the open space; click it to switch, or choose **New, rename, move…** for the
full list (also in Settings → Spaces). Luminary opens one space at a time, and switching reloads
the app. Each space has its own documents, notes, cards, study history, engine mode and model
picks, and its own name and colour. Paired devices, API keys and
downloaded models belong to the machine.

Removing a space asks you to type its id. It is refused for the default space, the open one,
and one a paired device still works in. A space this run of Luminary has opened is hidden at
once and its files deleted at the next start, because work it started may still be writing.

To move a space:

1. On the old machine, **Export** it to a sync folder: iCloud Drive, Dropbox, Google Drive,
   OneDrive or Box, whichever this computer has (into a `Luminary` folder inside it), or to
   `~/Luminary Exports/`. The archive is built elsewhere and moved in finished, so the sync client
   only ever uploads a whole one.
2. If you exported to `~/Luminary Exports/`, copy the file across yourself.
3. On the new machine, open Spaces: an archive in any of those folders is listed under
   **Import**. Import it under a folder name, then **Open** it. Every file is checked against the
   archive's hashes before the space is created, so an archive still downloading fails and
   leaves nothing. The result lists its documents, cards and notes to compare with the export.
   A file anywhere else imports through **Import a file from somewhere else**.

Only archives go into a sync folder. A space in use under a sync client corrupts: its database
journal and vector files change underneath the client.

| Refused, nothing written | Why |
|---|---|
| The importing Luminary is older than the exporting one | its database schema is newer than this version knows |
| The archive comes from a different embedder | its vectors are in another space; only a re-embed moves them |
| A name already in use, or `default` | an import never writes over a space |
| A damaged, truncated or half-synced file | a file fails its hash, or the archive does not read |
| A folder macOS has not let Luminary use | allow it under System Settings > Privacy & Security > Files and Folders |

The archive leaves out API keys and paired devices; enter keys and pair devices again on the new
machine. Models are not carried either: the new machine downloads its own at setup. Exporting
waits until no document is mid-ingestion. A Docker server writes its export inside the container;
copy it out with `docker cp`. A source install can also run
`python -m app.scripts.library_snapshot snapshot|restore` from `backend/`.

The two copies do not sync: studying on both machines afterwards gives two diverging spaces.

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
| `LUMINARY_ALLOWED_HOSTS` | *(empty)* | Names the server answers to beyond loopback; set, other machines need a device token |
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
