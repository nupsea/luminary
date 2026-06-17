# Luminary Phase 3 plan — one repo, one product, two hidden surfaces

Branch: `feat/redesign-1` (continues; Phase 2 landed here, Phase 3 builds on it)
Drafted: 2026-05-23
Supersedes: `redesign-phase-2-plan.md` (fully shipped), `redesign-phase-2p-plan.md` (folded into Track 3)

> **Frame.** Phase 2 made Luminary internally coherent. Phase 3 makes it externally legible. We stop building for three personas in parallel and commit to one public product (the learner-focused app) with two hidden surfaces inside the same repo: an eval harness aimed at engineers (top-of-funnel marketing) and a labs drawer for opt-in polymath features. No fork. No separate brand. No new repo.

---

## Guiding principles

1. **Learner is the only marketing surface.** Brand, README, screenshots, demo, install funnel — all aimed at students, lifelong learners, and self-directed studiers. Everything else stays in the repo but lives behind flags.
2. **Hide before you cut.** Polymath features (YouTube, audio, code parsing, web search, image enrichment, etc.) stay in code, gated to `labs`. Removal happens only after a release shows nobody opts in.
3. **One mechanism for visibility.** A single manifest decides which routes, services, and UI surfaces are `public | labs | dev`. No per-feature ad-hoc gating.
4. **Polymath features come back via user pull, not personal interest.** A learner saying "I want to study this YouTube lecture" promotes a labs feature; the author wanting to revisit a feature does not.
5. **Ship a real release.** The redesign branch becomes `v0.1.0`. A versioned, double-clickable artifact is the bar for "shipped," not "works on the author's machine."

---

## Track 1 — Labs-drawer architecture

The mechanism that makes one-repo-three-personas work. Extends `VITE_DEV_SURFACES` (Phase 2F.5) from a binary dev/prod toggle into a three-tier system.

**Full engineering spec:** `docs/labs-drawer-spec.md` — manifest schema, backend/frontend wiring, CI lints, migration plan, done bar.

| # | Change | Effort |
|---|---|---|
| 3.1.1 | **Visibility manifest.** Single source of truth at `frontend/src/lib/surfaceManifest.ts` listing every tab, route, and major service area with `tier: 'public' | 'labs' | 'dev'`. Mirrored in `backend/app/config.py` for backend-side gating. | small |
| 3.1.2 | **Three-tier env gate.** Replace `VITE_DEV_SURFACES` with `VITE_SURFACE_TIER = 'public' | 'labs' | 'dev'` (default `public` in prod builds, `dev` in `make luminary`). Backend mirrors via `LUMINARY_SURFACE_TIER`. | small |
| 3.1.3 | **Settings → Labs panel.** New section in `SettingsDrawer` listing labs-tier features with on/off toggles. Persisted to SQLite. Hidden entirely on `public` tier builds. | small |
| 3.1.4 | **Route + nav rail gating.** `App.tsx` reads the manifest and the user's labs prefs; lazy-loads only what's visible. Labs routes still resolvable via deep link on `labs` tier so existing bookmarks survive. | small |
| 3.1.5 | **Backend route gating.** FastAPI router registration in `main.py` consults the manifest. Disabled routers return 404, not 503; the surface should appear *not to exist* on `public` tier rather than appear broken. | small |
| 3.1.6 | **Manifest assignments.** Initial mapping: see "Surface inventory" below. | small |

### Surface inventory (initial manifest)

**`public` (learner product):**
Library · Notes · Study · Ask · Map · Progress · Luminary hub (`/`)
Backend: documents, notes, flashcards, study, qa, chat_sessions, summarize, search, sections, collections, tags, home, engagement, mastery, goals, settings, annotations, reading, references, graph (read-only views), pomodoro (if kept; see Track 2).

**`labs` (polymath, opt-in):**
Reader extras for code documents · Map advanced filters · Feynman/Teachback · Gap detection (graduated from labs if it proves usage) · Image extraction & enrichment · YouTube ingestion · Audio transcription · Web search · Code executor · Concept linker · Clustering / OrganizationPlanDialog · Tech-book parsing · Dataset generator UI.

**`dev` (engineering surfaces):**
Quality · Admin · Evals · Monitoring · ingestion-queue admin tools · model-usage dashboard · Phoenix link · RAGAS runner UI · eval regression service.

---

## Track 2 — Learner product polish

The narrow set of Phase 3 backlog items that *demonstrably serve the learner pitch*. Everything not on this list is dropped from the active queue.

| # | Change | Effort |
|---|---|---|
| 3.2.1 | **Backend mastery aggregate + mastery rings on `DocumentCard`.** Per-doc mastery percentage from `FlashcardModel.fsrs_stability`. Unlocks "weakest first" sort. Carried from Phase 2 deferred. | medium |
| 3.2.2 | **Decay-debt endpoint `GET /study/decay-debt`.** Surfaces cards approaching forgetting threshold. Drives a "What's about to slip" widget on the hub. | small |
| 3.2.3 | **Calibration delta tracking.** Predicted vs actual flashcard grade; metric on Progress. Cheap to add, lands a real learning-science differentiator. | small |
| 3.2.4 | **`reading_position` enrichment.** Persist scroll/page position per doc so "Continue reading" actually continues. Already half-wired via activity bumps. | small |
| 3.2.5 | **Session-shape inside Study (warm-up → engage → reflect).** Three-act review session, not an undifferentiated queue. The visible artifact of taking learning science seriously. | medium |
| 3.2.6 | **`⌘K` Ask panel with Socratic-default mode.** From any tab, `⌘K` → ask → answer back with citations. Default mode is Socratic (asks before telling) for learner audience; toggle for direct answer. | medium |
| 3.2.7 | **First-5-minutes flow audit.** Upload → summary appears → first card reviewed → first chat with citation. End-to-end manual run; fix every UX scratch. No new code likely; this is a *finish-the-edges* pass. | small |

### Dropped from Phase 3 backlog (do not pursue)

These were in the old plan's backlog. Each one steers the product toward the polymath direction or adds density without serving a learner-facing pitch.

- Atlas-style mastery overlay on Viz — Map is already an advanced surface; bolting mastery onto it is feature stack.
- Entity-as-tag reinforcement revival (2D.2) — known noisy; no learner asks for it.
- Auto-tag provenance distinction UI — engineering curiosity, not learner value.
- Pinned collections + manual ordering on the hub — activity-driven order is sufficient for v1.
- Pseudo-collections for loose docs / loose notes — adds a concept users haven't asked for.
- Batch memberships endpoint (`/collections/memberships?ids=…`) — inlined per-list is fine for current surface area.

---

## Track 3 — Packaging (was Phase 2P)

Folded in entirely. The redesign branch is not "shipped" until a non-technical user can run it.

### 3.3.A — Production runtime

| Item | Detail |
|---|---|
| `npm run build` | Verify it builds cleanly with `VITE_SURFACE_TIER=public` (Track 1 dependency). |
| Serve frontend from FastAPI | Mount `frontend/dist/` as `StaticFiles` at `/` in a `LUMINARY_MODE=prod` switch in `main.py`. API stays under `/api/*` or shares namespace. |
| One port | `uvicorn app.main:app --port 7820`, no `--reload`. CORS dropped. |
| `make build` / `make start` | New targets: build the bundle; launch the single-port prod server. |
| Health gate | Generalize `scripts/luminary.sh` ready-banner to poll one port. |

Effort: ~3 hours.

### 3.3.B — Versioned release

| Item | Detail |
|---|---|
| Version sync | `pyproject.toml` + `frontend/package.json` adopt `v0.1.0`. `scripts/version.sh` keeps them in sync. |
| `CHANGELOG.md` | Generated from the Phase 2 commit log (already structured). |
| Merge strategy | Squash-merge `feat/redesign-1` → `master` with the CHANGELOG entry; or merge-commit if per-commit detail matters. |
| Tag + GitHub release | `git tag v0.1.0` + push. Release notes pulled from CHANGELOG. |

Effort: ~2 hours.

### 3.3.C — One-command install

| Item | Detail |
|---|---|
| `scripts/install.sh` | Idempotent. Detects platform; installs `uv` if missing; installs `node` if missing (fnm/asdf); installs `ollama`; pulls `gemma4` + `llava:7b`; runs `make build`. |
| `scripts/start.sh` | Launches the production build with the existing ready-banner UX. |
| Intel-Mac Docker path | Carry forward the existing fallback in `scripts/luminary.sh`. |
| README rewrite | Replace 5-minute Quick Start with a one-paragraph install + run (paired with Track 5). |

Effort: ~3 hours.

### 3.3.D — Docker compose all-in-one

| Item | Detail |
|---|---|
| `Dockerfile.backend` | Multi-stage, `python:3.13-slim`, `uv sync`, exposes 7820. |
| `Dockerfile.frontend` | Build-only stage; dist files copied into the backend image's static path. |
| `docker-compose.yml` | Services: `backend` (serves frontend), `ollama` (`profiles: [ai]`). Volumes for `.luminary/`. |
| Intel-Mac | This becomes the canonical Intel-Mac path. |
| GHCR push | `.github/workflows/build-images.yml` builds and pushes on tagged releases. |

Effort: ~half-day. Depends on 3.3.A.

### 3.3.E — Desktop bundle (Tauri)

The version a non-technical user can double-click. **This is the "wider audience" gate.**

| Item | Detail |
|---|---|
| Tauri shell | Rust wrapper, ships the React bundle, runs the Python backend as a sidecar. |
| Sidecar lifecycle | Backend launched on app start, shut down on close; data lives in OS-appropriate user-data dir. |
| Code signing | Apple Developer ID + notarization for Mac. Required even for "send a friend a build." |
| Auto-update | Tauri's updater pointed at GitHub Releases. |
| Platforms | Mac first (Apple Silicon + Intel). Linux + Windows in a follow-on. |

Effort: ~3-5 days for a signed Mac bundle. +2-3 days each for Linux and Windows.

### Suggested execution order

1. **3.1 (labs drawer)** — required before A so `VITE_SURFACE_TIER=public` actually means something.
2. **3.3.A (prod runtime)** — required by C, D, E.
3. **3.3.B (versioned release)** — marks the redesign as shipped.
4. **3.2.7 (first-5-minutes audit)** — runs against the v0.1.0 bundle; fixes are v0.1.1.
5. **3.3.C (one-command install)** — high-leverage if anyone other than the author will run it.
6. **3.3.D (Docker)** — resolves Intel-Mac + future distribution path.
7. **3.2.1–3.2.6** — learner polish, paced across post-release minor versions.
8. **3.3.E (Tauri)** — its own phase. Revisit when v0.1.x has shown stability.

---

## Track 4 — Eval harness as satellite (top-of-funnel)

The eval harness is the *engineer-recruiting story* that funnels to the consumer product. It stays in this repo. It does not become its own brand, product, or company.

| # | Change | Effort |
|---|---|---|
| 3.4.1 | **`/evals` README.** Standalone README under `evals/` that pitches the harness to RAG engineers: golden dataset format, hybrid retrieval benchmarking, RAGAS thresholds as CI gates, Phoenix integration. Links back to Luminary as "the local-first learning app we built this for." | small |
| 3.4.2 | **Eval harness CLI polish.** `uv run python evals/run_eval.py --dataset X --backend-url Y` already works. Add `--export-html` to produce a shareable report. | small |
| 3.4.3 | **One blog-post-shaped artifact.** `docs/blog/local-rag-evaluation.md` — a write-up of "what we learned evaluating local RAG with three books and 70 golden Qs." Pointed at HN / r/MachineLearning / r/LocalLLaMA. Not marketing fluff; technical. | medium |
| 3.4.4 | **Repository top-level signposting.** `README.md` gets a short "For RAG engineers" section linking to `/evals/README.md`. Keeps the learner pitch primary; the engineer pitch is an offshoot. | tiny |

Out of scope: separate package, separate npm/PyPI publish, separate domain, separate license. The harness travels with the repo.

---

## Track 5 — Positioning surface

The repo currently reads as a personal project. Phase 3 fixes the framing without rewriting the code.

| # | Change | Effort |
|---|---|---|
| 3.5.1 | **README rewrite for learner audience.** Lead with the user story (study a book, get cited chat, FSRS-scheduled review, local-first). Move the architecture and contributing sections below. Quick Start becomes the install command (Track 3.3.C) + first-5-minutes flow. | medium |
| 3.5.2 | **Screenshot / demo capture.** Capture the first-5-minutes flow as still images + a short screen-cap. Embedded in the README and a hosted `docs/demo.md`. | small |
| 3.5.3 | **Landing-page placeholder.** A static `docs/site/` (or GH Pages) one-pager: tagline, three screenshots, install button, one paragraph each on Privacy / Learning Science / Open Source. No marketing site framework. | small |
| 3.5.4 | **Tagline + positioning sentence.** One line, used in the README, the GitHub repo description, the landing page, and the Product Hunt listing. Anchors every downstream surface. Decide before 3.5.1. | tiny |

---

## Explicitly parked in labs (not deleted from code)

These features stay in the codebase, gated to `labs` tier, hidden from the public bundle until learner-user signal requests them. No further iteration unless a request comes in.

- YouTube ingestion (`services/youtube_downloader.py`)
- Audio transcription (`services/audio_transcriber.py`)
- Code parsing + tech-book pipeline (`services/code_parser.py`, `tech_book_chunker.py`, `tech_section_parser.py`, `tech_relation_extractor.py`, `graph_tech.py`)
- Web search (`services/web_searcher.py`, `WEB_SEARCH_PROVIDER`)
- Code executor (`services/code_executor.py`, `routers/code_executor.py`)
- Image extraction + enrichment (`services/image_extractor.py`, `image_enricher.py`, LLaVA dep)
- Concept linker (`services/concept_linker.py`)
- Clustering / OrganizationPlanDialog (`services/clustering_service.py`, `components/OrganizationPlanDialog.tsx`)
- Feynman / Teachback (`services/feynman_service.py`, `feynman_strategies.py`, `components/Teachback/`, `routers/feynman.py`) — graduated to `public` if learner usage proves it
- Dataset generator UI (`services/dataset_generator_service.py`)
- Pomodoro (`services/pomodoro_service.py`, `components/FocusTimerPill.tsx`) — re-evaluate after first-5-minutes audit

---

## Done bar for Phase 3

- A user who has never seen the repo can install Luminary with one command (or one double-click), upload a PDF, review a flashcard, and have a cited chat — in under 10 minutes.
- The default install shows only the learner surfaces. No Phoenix tab. No Quality dashboard. No YouTube field. No Feynman session.
- `v0.1.0` is tagged, released, and downloadable.
- `/evals/README.md` is good enough that a RAG engineer who lands on it from HN stays for an hour.
- The labs drawer is the *only* mechanism for re-enabling parked features. No environment variables specific to individual features.
