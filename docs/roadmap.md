---
description: What is built, what is open, and what will never be built. The single place to look before proposing work. Read before starting anything not already covered by a live contract doc.
---

# Roadmap

Every other doc in `docs/` describes something that **exists**. This file is the only one that
describes work that does not, and it is the only place where status lives.

The rule that keeps it honest: **an implementation plan is deleted once its work ships.** The
code plus its live contract doc is the record; git history holds the plan. A shipped spec left
lying in `docs/` is indistinguishable from a live contract to anyone reading the tree for the
first time, and that ambiguity is more expensive than the plan is worth.

Each open item below carries evidence — a `file:line`, a gate, or a measured count. An item with
no evidence is an opinion and does not belong here.

## Shipped

The named doc is the live contract. The plan that produced the work is gone.

| Capability | Where its contract lives |
|---|---|
| Six-layer architecture, stores, surface modes | `architecture.md` |
| The 31 hard invariants | `invariants.md` |
| Backend implementation patterns | `patterns.md` |
| Ingestion + reading (all 4 reader phases) | `universal-reader.md` |
| Hybrid retrieval: RRF, cross-encoder rerank | `retrieval-funnel.md` |
| Concepts, mastery, the studyable atom | `concepts.md`, `concept-model-design.md` |
| Study orchestration, `POST /study/assemble` | `two-lane-model.md`, `study-launcher.md` |
| Signed macOS `.app`, notarized DMG, release flow | `desktop-bundle.md`, `releasing.md`, `release-credentials.md` |
| Client-side routing verification | `router-verification.md` |
| Notes: CodeMirror 6 editor, wiki-links, backlinks | `architecture.md` (nav section) |
| Hub recommender + misconception lifecycle | `recommender_service.py`, `misconceptions.py` |

Notes and the recommender shipped without a surviving contract doc because their behaviour is
adequately described by `architecture.md` plus the code. Their specs were deleted on
2026-08-11 under the rule above.

## Open

### 1. The frontend lint gate is not in CI

`make lint` runs `npm run lint`; `make ci` does not — it runs only `npm run build` and
`npx tsc --noEmit`. So the ESLint rules, including the `no-restricted-syntax` guard that forbids
raw `fetch()`, are advisory: nothing fails when they are violated.

Fix: add `npm run lint` to the `ci` target, then fix the fallout. Do this before item 2 — that
one is the measured consequence of this gate not running, and it will regrow if the gate stays
advisory. Items 3-5 are independent of it.

### 2. `apiClient` is bypassed by raw `fetch()`

**55 bare `fetch(` calls across 20 files** in `frontend/src`, of which 8 carry a justified
`eslint-disable`. Measured with `grep -rnE '(^|[^a-zA-Z.])fetch\('` — a naive `fetch(` search
reports 77 because it also matches `refetch(`/`prefetch(`, which are TanStack Query and are fine.

The 2026 quality audit measured 29 (`git show master:docs/refactor-quality-plan.md`, finding S6),
so this roughly doubled while the guard in item 1 was unenforced. Each bypasses `apiClient`'s
central error handling and base-URL resolution — the latter is what broke param-bearing GETs
under a relative `/api` base in production once already.

### 3. String-interpolated SQL

Six sites build `IN (...)` clauses by quoting values into the string rather than binding them:

- `services/vector_store.py:202,245,273`
- `services/retriever.py:189`
- `services/collection_health.py:98`
- `services/graph_view.py:60` — guarded by `.isalpha()`, so lowest risk of the six

Not currently exploitable: every interpolated id is internally generated. It is a latent
primitive that one change in id provenance turns live, and it defeats statement caching.

`graph_view.py:208,283,339,428` and `graph_tech.py:464` already bind `$name` placeholders and
are the pattern to copy. Do not "fix" those — they are already correct.

### 4. OKF is a grounding service, not yet a projection

`okf.md` describes a folder of Markdown files — one per concept, plus `index.md` and `log.md` —
as an export/import/grounding layer. Only the grounding half exists: `services/okf_context.py`
provides `resolve_concepts` and `build_concept_context`, consumed by `routers/qa.py`. There is
no file projection, no export endpoint, and no import path.

I-21 already governs the unbuilt half (OKF is a projection, never a transport and never a source
of truth), so build it against that invariant when it is built. `okf.md` is marked accordingly.

### 5. The `unstable` test quarantine

**28 tests across 15 files** carry `@pytest.mark.unstable` and are excluded from the default
run by `addopts`. Run them with `uv run pytest -m unstable`.

They are two different problems wearing one marker. Roughly half genuinely fail against the
current schema (the tag suite drifted). The rest pass individually but **cannot simply be
un-marked**: reclaiming them was attempted and failed — cancel-on-teardown wedges GitHub runners
into a mass error cascade, and grace-then-cancel pollutes shared Kuzu state, taking random
unrelated tests down with it.

Do not retry with timing policies. The durable fix is per-site coroutine neutralization, in the
style of the `_no_real_library_summary_generation` fixture, with opt-outs where a test genuinely
needs the background work (`test_e2e_upload` does).

Splitting the marker in two — `stale-schema` vs `leaks-tasks` — is the first step, because one
marker over two causes is why this has stalled twice.

## Deferred — decided, not scheduled

- **8GB low-footprint memory profile.** A profile plus model lifecycle management, explicitly
  *not* quantization. Write-only until someone commits to it.

## Abandoned — do not restore

Each of these was built, evaluated, and removed. They are listed so the next reader proposes
something else.

- **Universe / goal-driven knowledge model** — removed 2026-06-23. Zero references survive in
  `frontend/src/pages` or `backend/app/routers`. Do not restore the Universe lens, the Goals
  **nav tab**, or the `curriculum` router/service/models. A `goals` router does survive as a data
  source for the Hub surface; that is not the abandoned feature.
- **The three-tier `public | labs | dev` vocabulary** — replaced by one env knob,
  `LUMINARY_MODE=full|public`, declared per surface in `surface-manifest.json` (v2). The labs
  drawer, tiered-install and Phase 3 specs described the superseded design and were deleted.
- **`passes=true` and a reviewer gate** — named by I-13/I-14 for months; neither ever existed in
  the repo. The gates are `make ci` and `make smoke`. A gate name with nothing behind it is worse
  than no gate, because a claim to have satisfied it cannot be checked.
- **Two Ollama services** — rejected on a single-GPU/8GB machine. See I-31: enrichment cost is
  call count, not concurrency, so the lever is fewer calls, never more parallelism.

## Adding to this file

An entry is warranted when work is **decided but not done**, or **rejected and likely to be
re-proposed**. A bug is an issue, not a roadmap item. When an open item ships, delete its entry
and add a row to Shipped naming the doc that now carries the contract.
