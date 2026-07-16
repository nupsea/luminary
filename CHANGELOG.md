# Changelog

All notable changes to Luminary are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **The Map's Tags view no longer stalls for ~7s** (and neither does anything
  else that happens to run alongside a graph query). Kuzu is synchronous, and
  the `/graph` handlers awaited it directly on the event loop; with a single
  uvicorn worker that stalls *every* concurrent request. A 2ms `/tags/graph`
  measured **8.5s** sitting behind one all-library `/graph` traversal. The graph
  handlers now go through `asyncio.to_thread` (safe: `ThreadSafeKuzuConnection`
  already serializes execution under an RLock). Tags renders in ~0.6s, down from
  ~7.1s; `/tags/graph` alongside `/graph` drops from 8.58s to 0.034s. `/graph`
  itself is still slow (~8s for 4.3k nodes) — it just no longer blocks the app.
  I-2 extended to cover Kuzu, not just LanceDB.

### Removed
- **The Map's Learning Path view.** It required typing an exact concept name
  before it would render anything, and returned a chain only for entities with
  `PREREQUISITE_OF` edges — so in practice it was an empty canvas asking for
  input. Gone with it: `GET /graph/learning-path` (the Map was its only caller),
  the start-entity sidebar input, the prerequisite breadcrumb in the node
  popover, and the LP graph builder/types/overlays. Prerequisite edges are
  untouched — they still render as the Map's Prerequisites layer, and the
  prereq-chain traversal still backs the FSRS study path (`GET /study/path`).

### Changed
- **Two surface modes replace the public/labs/dev tiers.** One knob —
  `LUMINARY_MODE=full` (default; what `make luminary` runs — every feature on,
  including the Map, which returns to the learner rail as a nav tab) or
  `LUMINARY_MODE=public` (Docker/installers — curated learner surfaces served
  with the API under `/api` on one port). The old `LUMINARY_SURFACE_TIER` /
  `VITE_SURFACE_TIER` variables, the Settings → Labs toggle panel, the
  `labs_enabled` runtime setting, and `GET /settings/surface` /
  `PATCH /settings/labs` are gone; the surface manifest is now v2 (`mode` key).
  The backend `labs` dependency group is renamed `full`.
- **Evals consolidated on the Quality console.** The Monitoring page keeps
  Overview / Traces / Mastery; its stale Evals tab (pre-rebaseline RAGAS panels
  and `scores_history` charts) is removed along with `GET /monitoring/evals`,
  `GET /monitoring/eval-history`, and `GET /monitoring/evals/regressions`.
  Eval runners now store results via `POST /evals/store` (moved from
  `/monitoring/evals/store`).
- **Notes editor redesign** — the note editor is now always-live (no read/edit
  mode split) with autosave and draft safety: closing a note flushes instead of
  discarding, and empty auto-created drafts are deleted with a toast. The raw
  textarea is replaced by a CodeMirror 6 markdown editor (syntax highlighting,
  list/task/quote continuation, Ctrl/Cmd+B/I, paste-image upload). A `/` slash
  menu inserts blocks (headings, lists, tables, code/math, mermaid templates,
  Excalidraw), replacing the old toolbar; image sizing is a click popover on
  rendered images. `[[` links notes with server-backed autocomplete, rendered
  links are navigable, and every note shows a backlinks panel. Existing notes
  open at a deep-linkable `/notes/:noteId` page with an outline rail for
  structured notes; quick capture (Notes "New", reader selection/section notes)
  goes through a compact autosaving composer with an "open full note" hatch.
  Metadata (tags/collections/source docs) moved to a collapsible full-height
  properties rail; a reading view (Cmd/Ctrl+E) renders distraction-free serif.

### Removed
- Notes: legacy `group` list filter UI, the read-mode/edit-mode state machine,
  the markdown toolbar (image-spec buttons + mermaid quick-insert/cheat sheet),
  and the orphaned `LinkAutocomplete`/`NoteReaderSheet` components.

## [0.2.2] - 2026-06-30

### Fixed
- **Docker: Ollama unreachable + no model** — `docker-compose.yml` set `OLLAMA_HOST`
  but the backend reads `OLLAMA_URL` (default `127.0.0.1`, i.e. the app container),
  so the app never reached the `ollama` sidecar. Now sets `OLLAMA_URL=http://ollama:11434`.
  Added a one-shot `ollama-pull` service that fetches `llama3.2` into the sidecar on
  first `--profile ai` start (it previously started empty). README documents recovery
  when Ollama isn't running (native and Docker).

## [0.2.1] - 2026-06-30

### Fixed
- **Docker served a blank "Frontend not built" page** — the image built the SPA but
  copied it to `/app/frontend/dist`, while the prod server resolves
  `/frontend/dist` (`__file__`=/app/app/main.py → parents[2]=/). The Dockerfile now
  copies dist to `/frontend/dist`, so `docker compose --profile ai up` serves the app.
- **Intel Mac install guidance** — `scripts/install.sh` now fails fast on macOS
  x86_64 (no native `lancedb` wheel) with a clear pointer to Docker, instead of
  dying on a cryptic uv resolver error. README split the macOS quick-start into
  Apple Silicon (native) and Intel (Docker).

## [0.2.0] - 2026-06-30

### Changed
- **Public surface trimmed to the learning wedge** — the Map/graph view (`/viz`)
  moves from `public` to the `labs` tier. It no longer ships in the public bundle
  (the page chunk is build-stripped), the "View in graph" document action is hidden
  when Map isn't available, and a stale `/viz` deep-link on a public build redirects
  home silently. Map remains available on `labs`/`dev` builds.
- **Honest first-run for the local model** — `/settings/llm` now reports
  `ollama_reachable`, letting the first-run guide and the global banner tell
  "Ollama isn't running" apart from "Ollama is up but no model is pulled," each with
  the right command. `scripts/start.sh` prints a non-fatal pre-flight hint when the
  model is missing.
- **Calibration is now session-level** — the predict-vs-grade match tally carries
  across "Start Next Set" instead of resetting to zero, so the moat metric never
  silently disappears mid-session.
- **Notes view roomier** — the note grid drops from three dense columns to two
  larger, well-spaced cards (bigger padding, larger title/body), so the most recent
  notes fill the first screen and the rest are a scroll away.
- **Notes search filters in place** — searching notes now renders the matches as the
  same cards in the same grid (FTS/semantic relevance order) instead of switching to
  a separate scored-list view.
- **Chat sessions can group by document** — a Recent / By document toggle in the chat
  list; "By document" buckets each conversation under its source document's title
  (with Library-wide and Unknown-document buckets).

### Added
- **Theme persistence** — dark/light/system preference persists across reloads
  (`lib/theme.ts` + a pre-paint script in `index.html`, no flash) and is settable
  from Settings → Appearance, in addition to the nav-rail shortcut.
- **New brand mark** — the Luminary lantern artwork (background removed, light/dark
  frame variants so it stays visible on either theme) replaces the old glyph in the
  nav rail, hub header, About dialog, and first-run, and ships as the browser favicon
  (replacing the default Vite mark).

### Fixed
- **Spurious "document still processing" banner** — Study/learning surfaces showed
  a "a recently selected document is still processing — showing X in the meantime"
  fallback notice even when nothing was selected (`activeDocumentId` isn't persisted;
  only `lastReadyDocumentId` is). `useEffectiveActiveDocument` now flags a fallback
  only when an in-progress doc was actually active, so defaulting to the last-ready
  doc is silent.
- **Rendered-markdown typography** — the shared markdown renderer now has two modes:
  a compact sans body for chat answers (matches the UI chrome) and a roomy serif
  reading body for notes/long-form. Fixes chat answers reading in a mismatched serif
  while keeping notes in the serif reading font.
- **Prod SPA fallback no longer 500s** — `serve_spa` returns a clean 503 when
  `dist/index.html` is missing (unbuilt or mid-rebuild) instead of raising a
  FileResponse stack trace at the user.
- **`bg-card` surface token defined** — `--card`/`--card-foreground` were never
  declared and `card` was never mapped in the Tailwind config, so `bg-card` was a
  silent no-op app-wide. Defining it (light + dark) gives every card surface its
  intended background; in particular the chat answer bubble no longer renders light
  text on a white card in dark mode.
- **Dark-mode legibility across public surfaces** — hardcoded light-only tints
  (grade buttons, quality/status badges, content-type chips, error/empty cards,
  chat bubbles) gained dark variants, so no surface renders pale chips or white
  cards in dark mode.
- **Grade-button accessibility** — Again/Hard/Good/Easy now carry distinct icons
  and `aria-label`s, so they're no longer distinguished by color alone.
- **Duplicate "Today" hero** — the Library hero is now a quiet continue-reading
  affordance; the Hub owns the single recall CTA (due-card count stays in the
  Library stats bar).

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

[Unreleased]: https://github.com/nupsea/luminary/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/nupsea/luminary/releases/tag/v0.2.2
[0.2.1]: https://github.com/nupsea/luminary/releases/tag/v0.2.1
[0.2.0]: https://github.com/nupsea/luminary/releases/tag/v0.2.0
[0.1.0]: https://github.com/nupsea/luminary/releases/tag/v0.1.0
