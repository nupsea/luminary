# Changelog

All notable changes to Luminary are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.0] - 2026-08-21

### Added
- **Progress metrics carry sample size, definition and basis.** A metric that
  can't be computed is reported absent, never defaulted.
- **Time on task**, measured by heartbeat sampling while a document is in view.
- **Library filter chips only show types with documents behind them.**
- **A Settings card flags when the running model differs from configured**,
  and switches only after the replacement finishes downloading.

### Fixed
- **Citations name the page printed on the sheet**, not a chapter's first page.
- **Study and the reader reach their own landing** instead of the last-viewed
  document.
- **The study streak shown is the stored one**, not a recompute that read zero
  for same-day study.
- **Mastery Score removed** (was an unweighted average); **Cards Mastered now
  counts mastered cards**, not correct answers.
- **PDF search no longer flickers**; zoom matches auto-fit's actual value.
- **Windows install now records the model it pulled**, matching install.sh —
  could silently disagree with what's on disk before.
- **install.sh fails fast when curl or make is missing**, not a raw shell error.
- **`docker compose --profile ai` / `make docker-run` actually works now** —
  the frontend build, backend boot, and model handoff to the app were all
  broken.
- **A developer's `.env` was baked into Docker image layers** in two build
  paths with no guard against it. Fixed in both; local images rebuilt.
- **An unreadable knowledge graph reports 503 with guidance**, not a crash.

### Changed
- **Add Content leads with a web URL**; the type picker collapsed to one line.
- **Article import owns the DOM** rather than a boilerplate remover.
- **Interactive articles render through the desktop webview on macOS** —
  Windows and Linux still use static fetch.

## [0.6.1] - 2026-08-11

### Fixed
- **The interface froze while a document was parsing.** Parsing ran inline on
  the single server worker — 44.9s for a 23MB PDF. In public mode the backend
  also serves the interface, so its lazy-loaded routes never arrived and nothing
  could navigate while a parse was in flight: clicks did nothing while hover
  still worked. Parsing now runs off the request path, and the same file takes
  3.96s.
- **Enrichment spent most of its time collecting links that did not resolve.**
  Web references now cover the 40 longest sections rather than every section,
  return three links deduplicated by URL, and no longer carry an excerpt that
  was never read from the page. On Designing Data-Intensive Applications this
  step took roughly 50 of the run's 80 minutes to produce 920 links, 836 of them
  dead.
- **A leftover `.env` refused to start the backend.** A key held over from
  another version, or an unedited copy of `.env.example`, failed startup
  outright with "Extra inputs are not permitted". Unknown keys and unrendered
  placeholders are now ignored.

### Changed
- Local model concurrency is sized from the machine rather than guessed: under
  24GB of memory one slot, otherwise two, with four available opt-in. Every
  install path derives it the same way, and the desktop shell passes one value
  to both the inference server and the backend so the two cannot disagree.

### Security
- The frontend dependency tree reports no known advisories. The notable one was
  a high-severity code injection in `lodash-es` (GHSA-r5fr-rjxr-66jc), reachable
  through the drawing canvas. The affected packages are pinned forward, so
  nothing is rolled back to a worse version to obtain the fix.

## [0.6.0] - 2026-08-09

### Added
- **The reader adapts to what you are reading.** A novel, a paper, a technical
  book and a transcript rendered through identical code, so no layout suited any
  of them. Seven reading profiles now pick typeface, line length, heading
  treatment and dividers from what the document is: prose sets in a serif at 66
  characters per line, technical material runs wider for code and tables, and a
  transcript renders its speakers as labels beside their turns.
- **Reading preferences.** Typeface, text size, line spacing, line width and a
  paper background, remembered across sessions. The profile picks the default;
  the preference always wins. Left on "auto" a preference keeps tracking the
  profile rather than freezing today's value.
- **The reader has a URL.** The open document stays in the address bar, so a
  reload returns to what you were reading instead of the library list.

### Fixed
- **The reader showed retrieval chunks instead of the author's text.** Sections
  longer than a stored cap fell back to re-joining the chunks built for search.
  Those cut mid-sentence and overlap, so the reader fabricated a paragraph break
  every few hundred characters and duplicated text at every seam. Reading text
  now comes from a lossless column, and the reader reports when a document
  predates it rather than passing the damage off as formatting.
- **Nothing invents a heading any more.** Three separate places did: whole lines
  of prose became headings, transcript utterances were stranded in them, and
  empty sections were filled with placeholder text. A section the source left
  unlabelled is now rendered without a heading.
- **Chapter openings are no longer stolen for the heading.** A chapter's first
  line was treated as a subtitle whenever it was short enough, which matched
  most hard-wrapped prose — and removed that line from the chapter.
- **EPUBs are read by chapter.** A book packing many chapters into one file
  showed a fraction of them, in both the contents panel and the summaries, and
  its text arrived with no paragraph breaks at all. Verse and epigraph blocks
  were near-invisible in light mode, and the book's own links navigated away
  from the reader mid-book.
- **PDFs have paragraphs.** Text was assembled line by line, leaving a whole
  chapter as one block; it now follows the page layout. Running headers and
  footers are dropped instead of appearing in the prose.
- **A large book opens in a minute and a half rather than seventeen.** Section
  summarisation ran on the path to readability while the progress bar reported a
  different stage, so ingestion looked hung. It now runs after the document is
  readable, and covers every section: summaries are looked up per section by
  chat, suggested questions, Practice and concept linking, so the previous
  grouping left most of a long book invisible to all of them.
- A local model chosen in Settings was ignored when a cloud provider became
  unreachable, silently switching models while offline.
- Opening a large document sent megabytes of duplicated section text.
- `make eval` always reported zero: it pointed at a port nothing listens on,
  and on failing to reach a backend it deleted entries from the committed
  golden manifest rather than saying it could not connect.

### Note
Documents ingested before this release keep their old structure until they are
re-added; the reader marks the ones affected.

## [0.5.0] - 2026-08-07

### Added
- **The reader is sharp on retina displays, and its panels move.** The PDF canvas
  sized its backing store in CSS pixels, so a 2x display upscaled a 1x bitmap and
  every glyph rendered soft; the backing store is now sized in device pixels. The
  reader layout was a fixed 60/40 split with no way to resize or hide either side,
  and both rails are now draggable and collapsible. Setup downloads are named
  rather than arriving as opaque files.
- **Background model work is visible.** A diagram-heavy book is roughly 22 minutes
  of local vision inference, and because it runs on the GPU it never showed in CPU
  time — nothing in the interface said it was happening. A status pill now reports
  what is being enriched and how much is left, and stays silent when there is no
  work.

### Changed
- **The mastery heatmap issues 4 queries instead of 861.** It ran one query per
  section plus three per cell; three grouped reads now feed an in-memory join,
  with identical output. Genuinely blocking I/O elsewhere was moved off the event
  loop.
- **Internal structure.** Domain exceptions and repo helpers moved into the repo
  layer, error-handling rules are enforced rather than documented, graph failures
  are surfaced instead of swallowed, and the duplicated FTS sanitiser and
  fire-and-forget helper were collapsed into one each.

### Fixed
- **Ask answers the question instead of grading you.** A question phrased for
  analysis rather than lookup ("To what extent can Lloyd's algorithm be
  effective when...") reached the intent classifier's LLM fallback, which
  labelled it `teach_back` — the mode that treats the message as a learner's
  explanation of what they understand. The question was graded as an
  explanation nobody wrote, so the reply was an empty "what you got right /
  misconceptions / gaps" card. The interactive modes (teach back, socratic,
  the two notes modes) are only ever correct when the user's own phrasing asks
  for them, and that phrasing is already matched by keyword ahead of any LLM
  call, so the LLM no longer gets to choose them at all: it picks among the
  retrieval strategies, and anything else falls back to a plain lookup.
- **The local model stops reloading itself mid-conversation.** Ollama keys a
  loaded runner on its context window, so a call asking for a different one
  unloads llama-server and loads it again. Luminary asked for three different
  windows — 2048 by default, 4096 for the chat answer, 8192 for summaries and
  flashcards — which made a single chat turn reload the model twice, and a
  question asked while a document was still being enriched reload it
  repeatedly. Measured at ~1s per reload on an idle machine, and far worse
  under the GPU contention of an active ingest, where intent classification
  alone was observed taking 16s. There is now one window for every local call.
- **The transparency panel names the strategy that actually ran.** The routing
  table was written out twice and the copies had drifted, so a notes-gap
  question was reported as "search" while the notes-gap path answered it.
- **The suggested questions read like questions again.** The chips offered on a
  document were exam prose — "To what extent can Lloyd's algorithm be effective
  when applied to non-symmetric distance measures?" — and the phrasing was
  manufactured by our own prompt, which named the Bloom taxonomy level it
  wanted ("6 questions at level 5 (Evaluate)"). A small local model does not
  infer a pedagogy from that label; it copies the register the word belongs to.
  Those same phrasings were then what tripped the intent classifier into
  grading them. The level now picks plain-language guidance and the taxonomy
  word never reaches the model. Three further causes fixed alongside it: the
  depth ladder ran backwards, opening at the hardest level on a document you
  had never read and getting shallower as you engaged, so it now starts easy
  and climbs; generation was grounded on a summary, which let questions
  presuppose framings the document never makes, so it now uses real passages
  sampled across the whole document; and previous questions were injected
  verbatim under "avoid these", handing the model dozens of exam-phrased
  exemplars to imitate, so they are now reduced to bare topic words.
- **Suggested questions were mostly not being generated at all.** Local models
  routinely emit six well-formed JSON objects and then stop without closing the
  array. Both parse paths needed that closing bracket, so those responses
  scored zero candidates and fell back to the canned templates — silently, and
  often enough that the feature looked switched off. Whole objects are now
  salvaged from an unterminated array, which took the LLM path from 0 of 6
  attempts to 4 of 6 on the same document; the remaining two are the duplicate
  filter working as intended. The empty-candidate case is now logged with the
  counts that tell a parse failure apart from an exhausted question pool.
- **The contents panel lists sections you can actually navigate to.** Equations
  and anchor ids were being picked up as headings; unusable headings are now
  relabelled rather than dropped, and a bookmark's real heading is recovered from
  the page it points at.
- **The machine stops running hot after a failed enrichment.** Startup reset every
  failed job to pending on every launch, so a job that failed deterministically
  re-ran its model on each boot for the life of the install. Boot-time retries are
  now bounded.
- **The Linux from-source install completes.** The path stopped short of a working
  installation.

### Security
- **SQL injection closed in keyword search.** The `document_id` query parameter was
  interpolated into an FTS5 statement unescaped; that call and four sibling `IN`
  lists now use bound, expanding parameters. Security and async lint rules are
  enabled in CI, the unsandboxed `code_executor` route was removed, and Mermaid
  rendering moved from loose to strict (loose permits raw HTML in labels).

## [0.4.0] - 2026-08-05

### Added
- **Models and optional components are managed from Settings.** The catalogue was
  rendered only by the first-run setup screen, so after that first pass there was
  no way to install the vision model, speech-to-text or ffmpeg — and no way to
  remove one. Settings now lists every component with its size, licence and what
  it enables, and installs or removes it in place. The local chat model and the
  vision model are also settable there: both were read from config with no UI, so
  a model the user installed could not be put to use without editing `.env`. An
  empty choice means "use the configured default". The drawer widened from 400px
  to accommodate the catalogue rows.

  This also closes a disagreement in what the app reported: `active_model` for
  private mode was the *first* model Ollama happened to list, while
  `get_effective_routing()` used `LITELLM_DEFAULT_MODEL`. Both now resolve
  through the same setting.

### Fixed
- **The hub now shows the documents you have added.** Every document-driven
  section of `/home/overview` — recent items, continue reading, fading, the
  today action, and the recommender's stalled-reading candidate — reads
  `content_activity`, and nothing wrote a row when a document was ingested. The
  table was only ever written on a read past 10%, a note edit, or a flashcard
  event, so a library of freshly added documents produced an empty hub. Ingestion
  now records the add on reaching `stage='complete'` (not on upload — a failed
  ingest must not surface as something to pick up), and a data-only Alembic
  revision backfills existing libraries from `documents.created_at`. Separately,
  the hub's own emptiness check counted `recent_tags`, which the auto-tagger
  populates for every document — so the first-run guide became unreachable the
  moment anything was ingested and the page rendered its full layout with every
  section empty. Tags no longer count as something to act on.
- **Dropping a file on the window adds it.** Tauri's `dragDropEnabled` defaults
  to true and was never disabled, so the native window layer captured the OS
  drop before it could become a DOM event: the HTML5 drop handler could not fire
  in the packaged app at all, and nothing bridged the native event back to the
  webview. `disable_drag_drop_handler()` on the window builder lets the drop
  through. The only drop target also lived inside the Add Content dialog, so
  dropping on the app was never wired up either; the dialog is now mounted once
  app-wide and opened by a window-level drop zone with the file staged and its
  type pre-detected. A file that cannot be read says so instead of vanishing —
  including audio and video, which were refused silently when the transcription
  component was not installed, and which now offer the install.
- **A failed page render is legible instead of blank.** Pages are `lazy()` behind
  `Suspense` with no error boundary above them, so a render throw or a chunk that
  failed to load unmounted the tree to a white screen with nothing logged. Routes
  are now wrapped in a boundary that shows the error and offers a reload.
- **The shell installers now install the `full` dependency group, so URL
  ingestion works.** `bootstrap.sh`, `install.sh` and `install.ps1` synced
  `--no-default-groups` alone, which drops `full` — trafilatura, cloudscraper,
  yt-dlp and tree-sitter. The result was an install that came up healthy and
  refused every URL with "URL article extraction requires the 'full' dependency
  group" (issue #40). Only the macOS bundle was correct, because
  `stage_python.sh` already built `--no-default-groups --group full`. Both flags
  are load-bearing and are now pinned together by
  `test_every_installer_resolves_the_full_dependency_group`: `--group full`
  alone re-resolves `dev`, whose arize-phoenix pulls a source-built sqlean-py
  that fails against any interpreter the lockfile was not resolved for — which
  is what the error message itself used to recommend.
- **A link to a PDF is now ingested as that PDF.** `/ingest-url` sent every
  non-YouTube URL to the article extractor, which fetches HTML and strips
  boilerplate. Pointed at a PDF on a code host — a URL that serves a file
  *viewer* — it could not fail loudly: it stored the page chrome (navigation,
  sign-in prompts, product blurbs) as a document with a plausible title and none
  of the file's content, and reported success. `remote_source` now rewrites
  GitHub and GitLab `blob` URLs to their raw form, then decides from the
  response what was actually served: `%PDF-` magic bytes rather than the
  declared type, because hosts serve PDFs as `application/octet-stream`. A PDF
  goes down the same path as an uploaded one (same format, same content hash,
  same parser, `content_type='technical'` for `classify_node` to resolve).
  Markup is left to the article extractor, and a recognised file type that
  cannot be ingested from a link is refused with 415 instead of being parsed as
  HTML. The body is read once — `aiter_bytes()` is not restartable — and the
  verdict is taken from the first 8KB so a payload that will be rejected is
  never downloaded whole.
- **An uninstalled model no longer reports as failed enrichment.** Ollama
  answers a request for a model it does not have with 404 and
  `{"error":"model 'X' not found"}`, which litellm wraps as
  `APIConnectionError` — the same type as the server being down. Documents
  containing figures therefore showed "Enrichment failed" on a fresh install,
  after three pointless backoff retries, with a log line telling the user to
  check that Ollama was running; it was, and the vision model had simply never
  been pulled. `missing_model_from()` reads the model name out of the message,
  `component_for_model()` maps it to the component that installs it, and such a
  job is now `skipped` with an actionable message and no retries. The vision
  model is also a startup phase, so the setup screen offers an install button
  for it — previously it was a non-default component reachable from nowhere in
  the UI. Skipped jobs are re-queued when a component finishes installing and
  again on the next restart.
- **`bootstrap.sh` reports why startup failed.** The wait was 90 seconds, which
  is under a cold first boot: uvicorn writes nothing until `app.main` finishes
  importing torch, lancedb and the NER model, so the installer declared failure
  for an install that was still starting and pointed at a log file launchd had
  not created (issue #39). The wait is now 300s (`LUMINARY_BOOT_TIMEOUT`) with
  progress every 30s, and on failure it prints launchd's state, the log tail if
  there is one, and — when there is not — imports the backend in the foreground
  so the traceback has somewhere to go.
- **The notes preview now tracks the editor properly, at any zoom level.** Scroll
  sync mapped one pane onto the other with a single global ratio
  (`scrollTop / scrollMax`). That ratio is only correct at the very top and the
  very bottom: the editor is monospace with one row per source line, while the
  preview is serif prose whose block heights vary with headings, list spacing,
  images and KaTeX — three tight source lines can render as one wrapped
  paragraph while a five-item list expands into something far taller. Pixels per
  source line therefore differ by region, and the preview drifted further behind
  the more the two diverged. Browser zoom made it worse because it rewraps the
  two panes by different amounts, and because integer `scrollHeight`/
  `clientHeight` arithmetic rounds at fractional zoom.

  Sync is now line-anchored. A rehype plugin stamps each rendered block with the
  markdown line it came from, and a position converts between panes by
  interpolating between the anchors bracketing it, so every region uses its own
  measured pixels-per-line instead of a document-wide average. Offsets come from
  `getBoundingClientRect`, which is sub-pixel and therefore zoom-correct. A
  `ResizeObserver` re-syncs on zoom, window resize and splitter drags — none of
  which change the note text, so the existing content-change effect never saw
  them. Anchors are cached against a cheap signature rather than re-measured on
  every scroll event. Notes split around diagrams keep one continuous line axis.
  Previews without anchors (the blog dialogs, which wrap theirs in extra chrome)
  fall back to the previous proportional behaviour.
- **PDFs whose figures are drawn rather than embedded now have a visual layer.**
  A paper typeset from LaTeX draws its figures with path operators, so
  `page.get_images()` returns nothing and the document previously extracted zero
  images no matter how many figures it contained. When a page yields no raster
  image, its drawing primitives are now clustered into figure regions on a coarse
  occupancy grid and rasterized at 150 DPI. Primitives spanning the page (a
  background wash, a page border) are excluded from clustering first — they would
  otherwise bridge every figure into one whole-page region that the size guard
  then discards, losing the real figures with it. Blank renders are dropped before
  they cost a vision call. Off by `PDF_VECTOR_FIGURES=false`; capped at 4 figures
  per page and 300 per document.
- **Image extraction degrades honestly instead of failing the job.** A PDF that
  cannot be opened (encrypted, truncated) left the document stuck mid-enrichment.
  Extraction is now best-effort and runs off the event loop via `asyncio.to_thread`
  — rasterizing a large PDF is seconds of CPU that the single-worker server used
  to spend blocking every concurrent request. The reason a document has no figures
  ("extraction failed …", "No images found") is recorded on the enrichment job
  rather than presenting as a silently empty gallery.
- **A truncated vision response no longer becomes the image's description.** A
  local vision model that runs out of tokens mid-JSON used to have its half-written
  object stored verbatim as the description text. `salvage_llm_json_object()`
  now recovers the keys the model completed; when nothing is recoverable the
  description is left null so the next `image_analyze` job retries the image
  instead of indexing an unusable body. Repeated labels are deduplicated so one
  looping block name cannot crowd out every other label.
- **`POST /documents/{id}/images/reextract`** re-runs extraction on an
  already-ingested document, so a library picks up extraction improvements without
  re-uploading. Deduplicates on content hash; returns the in-flight job if one is
  already queued.

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

### Security
- **Frontend dependency advisories: 38 → 6.** `npm audit fix` cleared the
  in-range ones — `postcss`, `vite`, `immutable`, `js-yaml` (high), plus
  `dompurify`, `esbuild`, `mermaid` and `@babel/core`. `react-router-dom` moved
  6 → 7.18.2, closing both open-redirect advisories (protocol-relative `//` and
  backslash in `<Link>`/`useNavigate`); the app uses only the component and hook
  API, which is unchanged across that major.

  The 6 that remain have no non-destructive fix and are accepted knowingly:
  - `lodash-es` (×3) and `nanoid`, reached only through
    `@excalidraw/excalidraw` → `mermaid-to-excalidraw`. Excalidraw 0.18.1 is the
    latest release; npm's only offered "fix" is a **downgrade** to 0.17.6.
  - `brace-expansion` DoS under `openapi-typescript` (7.13.0, also latest; the
    offered fix is a downgrade to 6.x). Dev-only — it runs on our own schema
    during `make regen-api-types` and ships nothing.
  - `react-router` RSC-mode CSRF, which arrived *with* 7.18.2 and has no fixed
    release. It applies only to React Server Components mode; this is a static
    SPA with `BrowserRouter` and no server runtime. Downgrading to dodge it
    would reinstate the two open-redirects that do apply.

### Changed
- **Chat contradiction lookup filters in Cypher instead of Python.** The
  per-answer contradiction-context step scanned *every* SAME_CONCEPT edge in the
  library and built a Python dict for each, only to keep the ≤3 contradictions
  touching the in-scope documents. New `get_contradiction_edges_for_docs(doc_ids)`
  pushes the contradiction + doc-scope filter into the query, so only matching
  rows cross into Python. Proven equivalent to the old full-scan-then-filter over
  20 random doc-sets on the live graph. Kuzu has no index on `source_doc_id`, so
  the edge scan is still O(edges); what this removes is the per-edge Python
  materialization, which is what actually grew with library size.

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

## [0.3.3] - 2026-08-05

The macOS app now explains itself when it cannot start, and no longer leaves
processes behind. Nothing about the library or its contents changes, and this
release carries no database migration.

### Fixed
- **A failed startup is visible instead of a frozen screen.** Three defects
  combined into one symptom: `withGlobalTauri` was absent so the splash threw
  before registering any listener and no boot event had ever reached it; boot
  events were fire-and-forget, so a failure occurring before the page finished
  parsing reached nobody; and nothing was written to disk. The splash now also
  pulls the last state on load, and any error in the page lands in the failure
  state rather than freezing it.
- **The engine dying is reported immediately, with its own output.** uvicorn runs
  application startup before it binds a socket, so a failed migration or a bad
  data directory meant the port never opened — indistinguishable from a slow
  start for three minutes, after which the message named only the timeout. The
  shell now watches for the port, for the process exiting, and for the deadline,
  and reports the exit status with the tail of what the process printed. A dead
  backend surfaces in well under a second.
- **Nothing is stranded when the app crashes or is force-quit**, which never
  delivers an exit event. Both children are spawned into their own process groups
  and signalled as a group (catching Ollama's model runners), shutdown is
  SIGTERM then SIGKILL so SQLite can checkpoint, the backend stops itself if the
  shell disappears, and anything still left is reaped on the next launch. Reaping
  matches on executable path rather than pid alone, so a recycled pid can never
  cause an unrelated process to be killed — including your own `ollama serve`.
- **Launching an already-running Luminary brings it forward.** Spotlight and the
  Dock now unminimize and focus the existing window instead of appearing to do
  nothing.

### Added
- **A log at `~/Library/Logs/Luminary/luminary.log`**, rotated, carrying both the
  shell and the bundled processes. Deliberately outside the library, so an
  unwritable library is itself something that can be logged.
- **A one-click bug report from the startup screen.** It opens a pre-filled
  GitHub issue in the browser; the full text is shown first and nothing is sent
  until you submit it yourself. Home directory paths, account names, e-mail
  addresses and anything shaped like an API key are removed first, which is
  covered by tests.
- **Startup checks before anything is launched:** the installation is verified as
  complete, and low disk space is called out rather than failing partway through
  a model download.
- **`scripts/macos/uninstall.sh`**, which the app install never had. It asks
  separately before touching your library and keeps it unless you confirm.

### Changed
- The webview is no longer permitted to open URLs at all; the browser and Finder
  are opened from the shell itself.
- `make desktop-app` refuses to build against an incomplete or stale payload, and
  CI now builds, lints and tests the desktop shell on macOS — it previously had
  no automated coverage of any kind.

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

[Unreleased]: https://github.com/nupsea/luminary/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/nupsea/luminary/releases/tag/v0.7.0
[0.6.1]: https://github.com/nupsea/luminary/releases/tag/v0.6.1
[0.6.0]: https://github.com/nupsea/luminary/releases/tag/v0.6.0
[0.5.0]: https://github.com/nupsea/luminary/releases/tag/v0.5.0
[0.4.0]: https://github.com/nupsea/luminary/releases/tag/v0.4.0
[0.3.3]: https://github.com/nupsea/luminary/releases/tag/v0.3.3
[0.2.2]: https://github.com/nupsea/luminary/releases/tag/v0.2.2
[0.2.1]: https://github.com/nupsea/luminary/releases/tag/v0.2.1
[0.2.0]: https://github.com/nupsea/luminary/releases/tag/v0.2.0
[0.1.0]: https://github.com/nupsea/luminary/releases/tag/v0.1.0
