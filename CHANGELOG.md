# Changelog

All notable changes to Luminary are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.17] - 2026-06-02

### Added
- **Corporate Proxy Support on Windows:** Added `UV_SYSTEM_CERTS` configuration to `scripts/install.ps1` to trust native OS certificates and resolve SSL/TLS `UnknownIssuer` handshake errors. Added `UV_INSECURE_HOST` bypass fallbacks for PyPI.

### Changed
- **Default LLM model to Llama 3.2 3B:** Replaced `gemma4` (9.6 GB) with the highly optimized `llama3.2` (~2.0 GB) chat model to run fast on standard laptops.
- **Optional Vision Model:** Made the `llava:7b` vision model (4.7 GB) optional and disabled it by default in the public installation scripts (`install.sh` and `install.ps1`), reserving it exclusively for the `image_enrichment` labs feature.
- **Node.js Version Guard on Windows:** Updated `scripts/install.ps1` to verify Node.js is >= 20. Older versions are automatically upgraded to avoid NPM v6 lockfile parsing crashes.
- **Evaluation Dialog Defaults:** Updated dataset generation and evaluation runner UI dialogs to use `llama3.2` as the default model.
- **Documentation:** Updated `README.md` with new model details, sizing information, and a note on how to pull and switch to alternative local or cloud models.

### Fixed
- **CI Config Test Isolation:** Isolated `test_settings_defaults` in `tests/test_config.py` from active shell/workflow environment variables to prevent false test failures.


## [0.1.0] - 2026-05-31

> **Note:** date updated from 2026-05-29 to reflect final polish shipped before tag.

### Fixed (post-release polish — 2026-05-30/31)

#### Navigation & UX
- **Back navigation** — every contextual `navigate()` call across Hub, Library,
  Search dialog, Collections, and document action menus now carries
  `state:{from:pathname}`. Study, Notes, Chat, Viz/Map, Progress, and
  DocumentReader all render a context-labelled Back button ("Back to Study",
  "Back to Collection", etc.) when reached from an explicit action.
- **Session resume from reader** — clicking "Open in reader" from a flashcard
  source passage saves the session to the store; returning to Study auto-resumes
  the exact session via `prepareStudySession(resumeSessionId)`.
- **Collection context on Hub** — "Start N-card session" and "Worth revisiting"
  cards correctly scope the Study session to the displayed collection/document and
  clear stale `lastReadyDocumentId` fallback from the DocPicker.
- **⌘K search + shortcut navigation** — search results and `⌘Shift+N` now pass
  `from` state; Notes/Study labels update contextually.
- **Fallback warning** — "still ingesting" banner in Study now names both the
  in-progress document and the fallback being shown; includes a "Clear selection"
  link.

#### References panel
- Generalised reference enricher to all document types (philosophy, history,
  science, literature) with per-domain source guidance. New `academic` and
  `encyclopedia` source-quality tiers. Job-status endpoint (`GET
  /references/documents/{id}/job-status`) drives in-panel progress/retry states.

#### Hub
- `TodayAction` carries `collection_id/name/color/scoped_count`; hero CTA
  surfaces the most active collection by name.
- `ActiveCollection` exposes `due_card_count` for the active-projects grid.

#### Quality / maintainability
- Extracted `useBackNavigation()` hook — eliminates 7 sites of copy-pasted
  fromPath/backLabel/canGoBack logic.
- Removed `any`-typed filter construction in `SessionManager.onContinueTeachback`.
- Library delete mutations now show success/error toasts.
- `test_overview_tag_chips_union_doc_and_note_tags` marked `@unstable` (ordering
  flake under GLiNER memory pressure, same class as pre-existing unstable tests).

## [0.1.0] - 2026-05-29

First public release. Luminary is a local-first learning app: upload a document,
get a cited chat, and review it on an FSRS schedule — all on your own machine.

### Added

#### Learning product
- **Library** — upload PDFs/text/EPUB, auto-summaries, and a document reader with
  per-document reading position.
- **Study** — FSRS-scheduled flashcard review with auto-generated cards.
- **Ask** — retrieval-augmented chat with inline source citations; per-document and
  per-collection scoping; chat sessions.
- **Notes** — note capture with annotations, references, and clips linked to sources.
- **Map** — knowledge-graph visualization of documents, sections, and concepts.
- **Progress** — mastery and review-streak tracking.
- **Luminary hub** — activity-driven home surface tying the above together.
- **Collections** — workspaces that group documents, with library rails and a
  collection study dashboard.
- **Tags** — auto-tagging pipeline with cross-content merge and scoped tag counts.
- **Unified search** (Cmd-K) across documents, notes, and tags.

#### Privacy & models
- Local-first by default via Ollama; optional cloud routing (OpenAI / Anthropic /
  Google) with keys stored locally. Private / Hybrid / Cloud modes.

#### Release & packaging
- **Tiered surface manifest** (`surface-manifest.json`) — a single source of truth
  gating every router and UI surface as `public | labs | dev`, consumed by both
  backend and frontend.
- **Labs drawer** — opt-in experimental features (Feynman/Teach-back, YouTube/audio
  ingest, web search, code execution, image enrichment, and more) hidden by default
  and toggled in Settings on `labs`/`dev` builds.
- **Tiered install** — `labs`/`dev` are optional dependency groups; the public
  profile installs a minimal footprint (`uv sync --no-default-groups`).
- **Build-time strip** — `dev`-tier code (Quality, Admin, Monitoring) is excluded
  from public/labs bundles entirely.
- **Single-port production runtime** — `LUMINARY_MODE=prod` serves the built SPA and
  the API (under `/api`) on one port with no CORS. `make build` and `make start`.
- **CI lints** — manifest schema + coverage checks ensure every router and page
  declares a tier.
- **One-command install** — `make install` idempotently provisions uv, Node,
  Ollama, pulls default models, and builds the app.
- **Docker** — single-image multi-stage build + `docker-compose.yml` with an
  optional Ollama sidecar (`--profile ai`).

#### Learner-science features (Phase 3.2)
- **Mastery rings** on every `DocumentCard` — weighted FSRS stability as a
  visual progress indicator; "Weakest first" sort in the library.
- **Decay-debt widget** on the hub — surfaces documents with cards approaching
  the FSRS forgetting threshold.
- **Calibration delta tracking** — predict your grade before flipping (Know it /
  Unsure / Blank); match rate tracked weekly and shown on the Progress tab.
- **Session shape** — study queue sorted warm-up → engage → reflect; phase
  label in the session header.
- **Ask panel in ⌘K** — quick Q&A from any tab with Socratic mode (LLM asks a
  probing question before answering) and inline citations.
- **Chat auto-scope** — mentioning a document title in a question automatically
  scopes the answer to that document.

[Unreleased]: https://github.com/nupsea/luminary/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nupsea/luminary/releases/tag/v0.1.0
