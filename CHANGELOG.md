# Changelog

All notable changes to Luminary are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-25

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

[Unreleased]: https://github.com/nupsea/luminary/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nupsea/luminary/releases/tag/v0.1.0
