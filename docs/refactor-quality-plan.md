---
description: Refactoring plan for branch `refactor/code-quality-security-perf` -- clean code, interfaces, error handling, security, performance. Findings are measured; each carries the file:line that proves it.
---

# Quality, Security and Performance Refactor

Branch: `refactor/code-quality-security-perf` (from `master` at `32a5eb9`).

Every finding below is backed by a location in the tree. Counts come from
`ruff check app/ --select <rules>` and `npm run lint` on the branch point.

## Baseline

| Gate | State at branch point |
|---|---|
| `ruff check app/` (configured rules `E,F,I,UP,PL`) | green |
| `ruff check app/` (+`B,ASYNC,S,SIM,RUF,C4,TRY,PERF`) | 800+ findings, 12 of them `S608` |
| `npm run lint` (frontend) | **red -- 134 errors, 17 warnings** |
| `pytest --collect-only` | 2254 collected, 102 deselected |
| Backend `app/` | 502 tracked `.py`; services 31.7k lines, routers 14.3k |
| Frontend `src/` | 78.5k lines (18.5k is generated `types/api.ts`) |

The frontend lint gate is red on `master`. Nothing else in this plan matters if
CI does not actually run it -- WP0 fixes that first.

## Track S -- Security

| # | Finding | Location | Severity |
|---|---|---|---|
| S1 | Mermaid renders with `securityLevel: "loose"`, which permits raw HTML in node labels and `click` directives that invoke JS. The diagram text can originate from LLM output over an ingested document, so it is not all self-authored. `MarkdownRenderer.tsx:98` correctly uses `"strict"`; the blog export path does not. | `frontend/src/lib/blogMermaid.ts:22` | High |
| S2 | `httpx` call with no timeout. A hung remote holds the connection and a worker slot indefinitely. | `app/services/components.py:269` | Medium |
| S3 | Hardcoded `/tmp/` path for transcription intermediates -- predictable name, symlink and collision exposure on a shared host. Use `tempfile.mkdtemp`. | `app/workflows/ingestion_nodes/transcribe.py:117` | Medium |
| S4 | 12 raw SQL strings built by interpolation. `retriever.py:374` builds `IN (...)` by `", ".join(f"'{i}'" for i in ids)` with no escaping or parameterization. The IDs are internally generated today, so this is not currently exploitable -- it is a latent primitive that one change in ID provenance turns live, and it is also a performance defect (see P3). | `app/services/retriever.py:224,243,374,613`, `app/routers/tags.py:234,316`, `app/routers/home.py:182,200`, `app/repos/collection_repo.py:251`, `app/services/tag_graph.py:101,124`, `app/services/retriever_strategies.py:212` | Medium |
| S5 | DONE. The unsandboxed `code_executor` router, service, tests, and manifest entry are deleted. `stage_payload.sh` keeps the assertion as a reintroduction guard. | — | Done |
| S6 | 29 raw `fetch()` calls violate the existing `no-restricted-syntax` guard (only 8 have a justified `eslint-disable`). Each bypasses `apiClient`'s central error and base-URL handling. | frontend, 20 files | Medium |
| S7 | `md5` for content addressing (`article_extractor.py:98,283`) and `sha1` (`concept_nodes/persist.py:36`). Non-cryptographic use, but unmarked -- pass `usedforsecurity=False` so the intent is explicit and the scanner stays quiet. | as listed | Low |

Not changing: the server has no authentication and trusts the loopback boundary,
guarded by `TrustedHostMiddleware` (`main.py:274`). That is a deliberate,
documented design for a local-first app. CSRF remains deliberately open.

## Track E -- Exceptions and error handling

| # | Finding | Evidence |
|---|---|---|
| E1 | 309 `except Exception` handlers in `app/`. 20 are `try/except/pass` (`S110`) and 3 are `try/except/continue` (`S112`) -- silent swallows. Concentrated in `image_extractor.py` (12), `db_init.py` (11), `vector_store.py` (10). | `ruff --select S110,S112` |
| E2 | No shared exception module. Domain exceptions exist ad hoc in three services with unrelated hierarchies, and `SessionNotFound` is defined twice with different base classes. | `pomodoro_service.py:44`, `goal_service.py:69` |
| E3 | Services raise `HTTPException` -- business logic coupled to the transport. Worst instance is `repo_helpers.get_or_404`, which puts HTTP semantics underneath the repo layer (see I1). | `feynman_service.py`, `reference_enricher.py`, `repo_helpers.py` |
| E4 | 19 sites call `logger.error` inside an `except` where `logger.exception` is required -- the traceback is discarded, leaving unactionable logs. | `ruff --select TRY400` |
| E5 | 4 re-raises without `from` lose the causal chain. | `ruff --select B904` |
| E6 | "Returns [] on any error" as documented behavior: a Kuzu failure is downgraded to `logger.debug` and an empty edge list, so a dead graph leg renders as an empty map rather than an error. This is the failure mode [[feedback_verify_integrity_never_claim_artifacts]] exists to prevent. | `app/services/graph_tech.py:415,445` |

Target state: a single `app/exceptions.py` defining `LuminaryError` and the
domain subclasses, one FastAPI exception handler mapping them to status codes in
`main.py`, and services that raise domain errors only. A swallow must either
re-raise or log with `logger.exception` and a reason.

## Track I -- Interfaces and layering

`tools/layer_linter.py` runs in `make ci` and exits 1 on violations, but its
`LAYER_ORDER`/`SUBDIR_MAP` had no entry for `repos`, `schemas` or `runtime`.
Those three resolved to `None`, which the checker treats as "unclassified --
skip", so half the backend was exempt and all 10 violations below reported
clean. Fixed on this branch: the maps now cover every layer, and a
`KNOWN_VIOLATIONS` allowlist carries the existing debt so the gate is green
without hiding it. Verified by deleting an allowlist entry and confirming
exit 1.

| # | Finding | Evidence |
|---|---|---|
| I1 | **Backward import, 8 occurrences.** Every repo imports `app.services.repo_helpers.get_or_404` -- Repo depending on Service, which `architecture.md` calls a build failure. Move it to `app/repos/_helpers.py` and strip its `HTTPException` (E3). | `collection_repo.py:15`, `tag_repo.py:26`, `clip_repo.py:15`, `note_repo.py:28`, `flashcard_repo.py:22`, `study_repo.py:31`, `document_repo.py:32`, `annotation_repo.py:16` |
| I1b | `schemas/documents.py:14` (Types) imports `workflows.ingestion` for the `ContentType` enum; `services/qa.py:464` lazy-imports `runtime.chat_graph`. Both in `KNOWN_VIOLATIONS`. | as listed |
| I2 | 13 routers import repos directly. Legitimate for thin CRUD, but it is how business logic reaches the router layer: `study.py` holds 2407 lines, 31 endpoints, 101 direct DB calls, and 15 private business-logic functions. | `app/routers/study.py` |
| I3 | `models.py` declares zero `relationship()` and the codebase uses zero `selectinload`/`joinedload`. Every association is hand-joined. This is correct for async SQLAlchemy (lazy loads raise `MissingGreenlet`) but is undocumented, and it is the direct cause of the N+1 loops in P1. Document it in `patterns.md` rather than "fixing" it. | `app/models.py` |

## Track P -- Performance

| # | Finding | Location | Impact |
|---|---|---|---|
| P1 | N+1, quadratic. `get_heatmap` issues one query per section, then a `LIKE '%concept%'` query per (section, concept) pair. Cost is O(sections x concepts) round trips. | `app/services/mastery_service.py:343-360` | High |
| P2 | 22 blocking `pathlib` calls and 1 blocking `open()` inside async handlers; 11 are on the file-serving endpoints in `documents.py`. The server runs a single worker, so each blocking `stat`/`read` stalls every concurrent request -- the exact failure I-2 already forbids for LanceDB and Kuzu, unenforced for the filesystem. | `documents.py` (11), `images.py` (3), `main.py` (2), others | High |
| P3 | Unbounded interpolated `IN` list defeats statement caching and grows the SQL text with the result count. Parameterize and batch. | `app/services/retriever.py:374` | Medium |
| P4 | Per-row `INSERT OR IGNORE` in a loop where one `executemany` would do. | `app/services/notes_service.py:299` | Medium |
| P5 | 17 manual list-append loops that are list comprehensions (`PERF401`). | `ruff --select PERF` | Low |
| P6 | 103 `.execute()` calls across `graph_*.py` against 66 `asyncio.to_thread` wraps app-wide. Which graph calls sit on an async path unwrapped needs a per-call audit -- I-2 makes any unwrapped one a stall. | `app/services/graph_*.py` | Audit |

## Track C -- Clean code and cleanup

| # | Finding | Location |
|---|---|---|
| C1 | **Duplicated block.** `_teachback_eval_sem` and `_fire_and_forget` are each defined twice, and `_background_tasks` is referenced at line 147 before its definition at line 151. Copy-paste artifact; delete lines 150-162. | `app/routers/study.py:139-162` |
| C2 | `_fire_and_forget` duplicated across 5 files, `_to_response` across 5, `_sanitize_fts_query` across 3. The FTS sanitizer is correctness-critical -- `patterns.md` documents exactly how it must behave, and three copies is three chances to diverge. | backend-wide |
| C3 | 225 unused `# noqa` directives. Each one hides whether the rule it suppresses still applies. `RUF100` autofixes these. | `ruff --select RUF100 --fix` |
| C4 | Frontend lint red: 41 `no-explicit-any`, 29 raw `fetch`, 18 `react-hooks/refs`, 14 unused vars, 12 `set-state-in-effect`, 10 `exhaustive-deps`. Partly fixed in WP0 -- see "Frontend gate" below. Remaining 125 are pinned as warnings. | `npm run lint` |
| C6 | `App.tsx:569` opened a JSX comment with the word "global". ESLint reads `/* global ... */` as a directive wherever it appears, so `focus`, `timer` and `pill` were declared as globals and then reported unused. Reworded. Nothing else in `src/` starts a comment with `global`. | fixed |
| C7 | Four `eslint-disable-next-line` comments named `react/no-danger` and `jsx-a11y/media-has-caption`, whose plugins are not installed. An unresolvable rule in a disable comment is itself an error. Removed. | fixed |
| C5 | Files past the point of navigability: `study.py` 2407, `documents.py` 1691, `evals.py` 1408, `Chat.tsx` 1563, `DocumentReader.tsx` 1492, `Notes.tsx` 1428. | as listed |

## Work packages

Ordered so guardrails land before the cleanups they protect. Each WP ends green
on ruff, pytest, tsc and eslint (I-13 order).

| WP | Contents | Risk |
|---|---|---|
| **WP0 -- Guardrails** | DONE. See below. | Low |
| **WP1 -- Security** | DONE. See below. | Low |
| **WP2 -- Interfaces** | I1: move `repo_helpers` under `repos/`, drop `HTTPException` from it. E2/E3: add `app/exceptions.py` + one handler in `main.py`; convert the three ad-hoc hierarchies. Document I3 in `patterns.md`. Correct or enforce the "mechanically enforced" claim in `architecture.md`. | Medium |
| **WP3 -- Error handling** | E1 triage: every `except Exception` gets narrowed, re-raised, or logged with `logger.exception` and a reason. E4, E5, E6. Start with `image_extractor.py`, `db_init.py`, `vector_store.py` (33 of 309). | Medium |
| **WP4 -- Performance** | P1 (single grouped query for the heatmap), P2 (`to_thread` the file-serving paths), P3, P4, P6 audit. Measure P1 and P2 before and after; record the numbers here. | Medium |
| **WP5 -- Cleanup** | C1, C2 (extract shared helpers -- `_sanitize_fts_query` first), C3, C4. C5 is split out: `study.py` -> extract the 15 private functions into `services/teachback_service.py` and `services/study_session_service.py`. | Medium |

C5's frontend half (`Chat.tsx`, `DocumentReader.tsx`, `Notes.tsx`) is deliberately
not in this plan. Splitting three 1.4k-line components is its own branch with its
own regression surface.

## Shipped in WP0 + WP1

Backend `ruff check .` green, `layer_linter` green, 2240 tests pass,
`tsc --noEmit` clean, `npm run lint` 0 errors.

**Ruff.** Added `B,ASYNC,S,SIM,RUF,C4,TRY,PERF`. `B008` is off permanently (it
is the FastAPI `Depends()` idiom). `RUF100` is off because `# noqa: PLC0415`
marks a deliberate lazy import per I-5, and PLC0415 is globally ignored -- the
rule would have stripped all 152 markers. Deferred rules are listed individually
with their WP; removing a line is what re-opens the work.

**Layering.** `tools/layer_linter.py` now classifies `repos`, `schemas` and
`runtime` (see Track I).

**Frontend gate.** `npm run lint` now runs in `make lint`, pinned at
`--max-warnings 125`. Errors fail the build; the 125 deferred findings are
warnings that cannot grow. `no-unused-vars` gained an `^_` ignore pattern,
which is what 11 of the 14 "unused variable" errors actually needed.

**Security fixes.** `blogMermaid.ts` `securityLevel` loose -> strict; a real SQL
injection closed in `HybridRetriever.keyword_search` (a `?document_id=` query
param was interpolated into the FTS5 statement unescaped) plus four sibling
`IN` lists converted to `bindparam(expanding=True)`; `install_ollama_model`
given an explicit `httpx.Timeout`; transcription temp files moved from a
predictable `/tmp/{doc_id}` path to `tempfile.mkdtemp` with cleanup in a
`finally` (the ffmpeg-failure path leaked the directory before);
`usedforsecurity=False` on three content-addressing hashes; `code_executor`
deleted.

**Correctness found while fixing.** `zip()` calls gained `strict=True` rather
than ruff's suggested `strict=False`, which surfaced a NER test whose mock
returned `[]` for one input chunk where the real model returns one list per
input; a bare `asyncio.create_task` in `tags.py` held no strong reference and
could be garbage-collected mid-scan; a blocking `open()` write in the image
upload handler now goes through `asyncio.to_thread`; `_extract_docstring_python`
used `.strip('\"\"\"')`, which strips a character set and ate quote characters
belonging to the docstring text.

## Out of scope

- Adding authentication. The loopback trust boundary is the design.
- Restoring the Universe/Goals model. Removed 2026-06-23, stays removed.
- Reclaiming the 15 genuinely-failing `unstable` tests -- prior attempt failed
  and must not be retried with timing policies.
