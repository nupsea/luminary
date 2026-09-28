---
description: What is built, the features coming next, and what will never be built. The single place to look before proposing work. Defects live in the issue tracker, not here.
---

# Roadmap

Every other doc in `docs/` describes something that **exists**. This file is the only one that
describes work that does not, and it is the only place where status lives.

The rule that keeps it honest: **an implementation plan is deleted once its work ships.** The
code plus its live contract doc is the record; git history holds the plan. A shipped spec left
lying in `docs/` is indistinguishable from a live contract to anyone reading the tree for the
first time, and that ambiguity is more expensive than the plan is worth.

**Defects are issues, not roadmap items.** This file had drifted into a defect log against its
own rule; on 2026-08-29 the nine that were left moved to the tracker
([#95](https://github.com/nupsea/luminary/issues/95)–[#103](https://github.com/nupsea/luminary/issues/103)),
along with the evidence each carried. The test-suite quarantine lives in
[#50](https://github.com/nupsea/luminary/issues/50).

What belongs here is a **feature large enough to change what Luminary is for** — something a
user would notice arriving, that needs a decision before it needs code. Each entry says what
already exists, because the hard part is usually a constraint rather than the build.

## Shipped

The named doc is the live contract. The plan that produced the work is gone.

| Capability | Where its contract lives |
|---|---|
| Frontend lint as a CI gate | `Makefile` `ci` target, `frontend/eslint.config.js` |
| Six-layer architecture, stores, surface modes | `architecture.md` |
| The hard invariants | `invariants.md` |
| Backend implementation patterns | `patterns.md` |
| Ingestion + reading (all 4 reader phases) | `universal-reader.md` |
| Hybrid retrieval: RRF, cross-encoder rerank | `retrieval-funnel.md` |
| Concepts, mastery, the studyable atom | `concepts.md`, `concepts.md` |
| Study orchestration, `POST /study/assemble` | `two-lane-model.md`, `study-launcher.md` |
| Signed macOS `.app`, notarized DMG, release flow | `desktop-bundle.md`, `releasing.md`, `releasing.md` |
| Client-side routing verification | `patterns.md` |
| Notes: CodeMirror 6 editor, wiki-links, backlinks | `architecture.md` (nav section) |
| Hub recommender + misconception lifecycle | `recommender_service.py`, `misconceptions.py` |
| Flashcard source grounding: per-card verdict, deck audit, review-time display | `invariants.md` I-34 |
| Flashcard factuality gate + recorded passage (`source_chunk_ids`) | `invariants.md` I-35 |
| Learner-facing metrics carrying sample size, definition and basis | `metrics.md` |
| An existing install carried to the model its host should run: Windows records what it pulled, a Settings card surfaces drift and switches only after the download completes | `model_router.narrowed_defaults()`, `ModelDriftNotice.tsx` |
| Content-type classification, scored against a labelled corpus rather than asserted | `services/content_classifier.py`, `tests/fixtures/content_type_labels.json` |
| Image extraction and vision enrichment, including the vector-figure fallback and its over-extraction guards | `invariants.md` I-38, `services/image_extractor.py` |
| Model footprint measured rather than estimated, three RAM bands, and a registry that refuses a model the host cannot hold | `model_registry.py`, `metrics.md` |
| Interactive work outranks background work for the Ollama slot | `services/llm_admission.py`, `tests/test_background_yields_the_slot_to_a_waiting_question.py` |
| Eval runs carry their own provenance (model, embedder, corpus fingerprint, library state) and a repair/first-pass tier | `evals/run_eval.py` `capture_environment`, `GET /evals/output-stats` |
| Documents carry three facets (form, domain, register) behind one derived profile, written at ingest and readable per document | `types.py` `DocumentProfile`, `workflows/ingestion_nodes/parse.py` `_persist_classification` |
| A citation lands on its passage -- marked, centred and held there -- in prose, transcripts and as an overlay on the PDF page itself | `invariants.md` I-41, `frontend/src/lib/citation/`, `make verify-citation` |
| Engine modes (private, hybrid, cloud), the engine offer, the privacy receipt, and the supported-host policy (0.10.0) | `engine-and-hosts.md` |
| The docked reader panel: faces, per-type citations, docked chat and composer, live markdown, the in-reader practice loop (0.11.0) | `reader-panel.md`, `make verify-dock` |

Notes and the recommender shipped without a surviving contract doc because their behaviour is
adequately described by `architecture.md` plus the code. Their specs were deleted on
2026-08-11 under the rule above.

## Roadmap

**1.0.0 is a major public release, reached through a ladder of minor versions.** Each rung carries
one theme, one exit gate that can come out red, and leaves the app whole if the rung after it never
ships. Patch numbers are release plumbing here — 0.8.0 to 0.8.28 took one day — so the minor is the
planning unit. Rung numbers are ordering, not commitments; several will split once scoped.

**1.0 is a production-grade local-first app on every host, that the user can also run on their own
server and read from their phone.** The ladder runs stability, then cloud readiness, then component
separation, then the mobile client, then Anki and the extras, then languages. Decided 2026-09-27:

| Decision | Consequence |
|---|---|
| Cloud in 1.0 is **self-hosting**: each user runs their own server, with device-token auth and their own API key | A paid hosted multi-tenant version follows 1.0. 0.17.0 builds the seams it needs now, so that work starts with negligible debt |
| Mobile data comes **from the server, with an offline cache**: the phone talks to the user's server or a paired desktop, and keeps a local cache and an outbox for offline writes | Sync through storage the user controls (iCloud, Dropbox) is after 1.0 (Deferred) |
| The mobile client is **Tauri 2 mobile**, reusing the React + Vite frontend | `frontend/src` imports nothing from `@tauri-apps`, so separation (0.19.0) is a refactor rather than a rewrite |
| **Pairing is built now, the capture extension later** | Device auth lands in 0.16.0; the extension moves to 0.21.0 |

**One authentication mechanism, built in 0.16.0, serves your own server, mobile and the capture
extension.** Building it per consumer produces three trust models that disagree.

Feature rungs land on a suite with a live quarantine, so **a rung ships its smoke scripts with its
endpoints (`CLAUDE.md`) and adds nothing to the quarantine**. The quarantine grew once — 22 to 23
markers on 2026-09-18 (`fcfb4e5d`, a `POST /notes` case in `test_S201.py`) — which is why the gates
rung sits ahead of every feature rung.

Every rung also starts with a refactor of what it is about to change ("Code quality to 1.0", below).

The last rung of each phase is a **checkpoint release** (below): the whole product is measured on
one build, not only the rung that just landed. The issues listed against a rung are the ones its
exit gate cannot pass without; tracking rules are in "Bugs to 1.0" below.

| Phase | Rung | Theme | Issues | Exit gate |
|---|---|---|---|---|
| — | 0.10.0 | Smart Hybrid, and the privacy receipt — **shipped** | | Time to first token measured on both arms from a cold install and reported as a pair; a test proves that only the question and its packed passages leave the machine |
| — | 0.11.0 | The docked reader — **shipped** | | A passage captured in the reader resolves back to its locus for page, video and web; no modal opens from the reader |
| — | 0.12.0 | The Brief — **parked** | | None; no rung waits on it |
| I. Every host | 0.13.x | Every host is a first-class host — **0.13.9 released; exit gate open.** **Checkpoint A** | #24, #99, #110, #154, #155, #156 | First run completes with no terminal on a Windows and a Linux machine that has never seen Luminary, and each is told the truth about its own accelerator; `make smoke` green on Windows and against the bundled macOS app |
| II. Stability | 0.14.0 | Gates you can believe | #50, #101, #88, #157 | `make ci` and `make smoke` both green, nothing quarantined to keep them so; the code-quality ratchets run in `make ci` |
| | 0.15.0 | Stores that agree, output you can measure. **Checkpoint B** | #65, #63, #97, #100, #66, #158, #159, #160, #161, #162 | A reprocess killed midway leaves no divergence between stores; every ingest path reports a measured fidelity number; no shipped default changes what a user receives without a number behind it; zero open `bug` issues milestoned to Phase I or II |
| III. Cloud readiness | 0.16.0 | Device auth and pairing | | An unpaired origin or a revoked device is refused, proven by a test that fails when pairing is removed |
| | 0.17.0 | An architecture that can take tenants; snapshot/restore; the re-embed rail | #48 | Every request resolves a principal and a library; a second library is fully isolated in tests; a killed re-embed resumes; a snapshot restores |
| | 0.18.0 | Your own server. **Checkpoint C** | | A container reachable beyond loopback refuses every request without a device token; a CPU-only server builds an enriched library with a key |
| IV. Separation | 0.19.0 | Components separated for mobile | | A Tauri mobile shell builds in CI and its shared UI packages pass tsc and vitest; the backend change feed passes a contract test; no raw `fetch(` outside `apiClient` |
| V. Mobile | 0.20.0 | Topic notes and the draft inbox; mobile reading and note capture. **Checkpoint D** | #173 | A merge that leaves a source note out of every section is refused, a summary claim no source note supports is flagged, and undoing a merge restores every original; a phone reads cached documents and writes notes offline; the notes reach the server on reconnect with none lost or duplicated |
| VI. Extras | 0.21.0 | Anki import; the capture extension, watch folder and Obsidian export; card review on mobile | #137, #124, #121, #25, #103, #26 | No imported card shows a grounding verdict it did not earn, and its schedule comes from FSRS state; three source types round-trip from the browser to a readable document; an offline review on the phone merges without overwriting FSRS state |
| VII. Languages | 0.22.0 | Multi-language — **conditional** | | Non-English degradation measured on the current stack first; a swap ships only through 0.17.0's rail; a no-go decision is an allowed outcome and moves the swap to 1.1 |
| | 1.0.0-rc → 1.0.0 | The release. **Checkpoint E** | | Zero open `bug` issues; every rung's exit gate green together, on one build; the code-quality targets met |

**1.0.0 itself carries no new features.** Work not on a rung above is 1.1, not 1.0.

### Checkpoint releases

A rung release proves its own exit gate. A checkpoint also proves that nothing already shipped
broke on the way, which no single rung is responsible for. It is the phase's last minor release
(`releasing.md`), tagged only after all of the following pass on the build being tagged:

| Layer | What must be green |
|---|---|
| Suite | `make ci` locally and on GitHub; `windows-host-policy` and `desktop-shell-windows` in `ci.yml` |
| Contract | `make smoke` against the bundled app on macOS and on Windows |
| Retrieval and generation | `make eval-all`, plus `make eval-notes`, `make eval-summary` and `make eval-flashcards`, each compared with the previous checkpoint's rows in `scores_history.jsonl` on the same corpus fingerprint (a different fingerprint is not a comparison) |
| Reader | `make verify-dock` and `make verify-citation` |
| Latency | `make measure-ttft`, both arms, reported as a pair |
| Installers | `desktop-installers.yml` green for Windows and Linux; the DMG built and launched on a cleared data directory (`releasing.md`, "Before tagging") |
| Upgrade | A library last opened by the previous checkpoint opens on this build. Migrations are one-way (`releasing.md`), so this is the only point where a broken upgrade can still be caught before users run it |
| Manual | On a machine that has never seen Luminary, per platform: install with no terminal, first run, ingest one PDF, EPUB, audio file, YouTube link and web page, ask a question and follow a citation, run a practice session, write a linked note, quit and relaunch |

A gate that could not run is a failure, not a skip (`eval-integrity`). The checkpoint's release
notes name what was not exercised, such as a GPU vendor or an OS version nobody had.

Startup only ever runs `upgrade head`, so a newer library cannot be opened by an older build
(`releasing.md`). Every migration is a one-way door, which is why what remains of the document-model
work and the re-embed rail both stay inside 0.x.

### 1. The Brief — 0.12.0, parked

A per-document thesis and claims, each quoting its passage. **Parked: no rung waits on it and no work
is scheduled before 1.0.** The thesis and claims are built and unmerged on `feat/the-brief`; that
branch's copy of this section carries the support measurements and what was open.

If it is picked up, two constraints still hold. A claim that copies its quote passes any judge, so
support is only quotable beside a near-copy rate. The suggested questions are #66:
`SuggestionService.get_grounding_passages` prefers `SectionSummaryModel.content`, so each question
must be generated from chunk text and validated by retrieval before it ships.

### 2. Every host is a first-class host — 0.13.x

A public 1.0 that runs on one operating system is a beta with a version number. The macOS bundle is
signed and notarized; Windows is #24 and Linux has no bundle at all. This rung is what makes the
support policy shipped in 0.11.2 true on the two platforms it cannot currently see.

**The policy now runs on the platform it got wrong, narrowly.** The probe branches per platform —
Windows reads the driver libraries Ollama loads, everywhere else keeps the device-node check — held
by platform-pinned tests, five of which redden when the Windows branch is removed, plus one that
calls the real probe on whatever host is running it and asserts no verdict. `windows-host-policy`
in `ci.yml` runs `uv sync --frozen`, an import of `app.main`, and those tests on `windows-latest`.
`--frozen` deliberately: a lock that does not resolve on Windows is the defect the job exists to
surface, and `install.ps1` runs the same step on every Windows install. **It runs green**: the lock
resolves on Windows, `app.main` imports, and the policy answers there.

**What the job does not claim is the rung.** It proves the dependency step resolves, the app
imports, and the policy answers. `make ci` and `make smoke` green on Windows are this rung's exit
gate, and widening the job to them is where the rest of the Windows work will show up — path
handling, the Kuzu lock, and whatever the suite assumes about `/`.

Keep one probe with a branch per platform. A second copy of the policy would eventually disagree
with this one, and the copy a user meets is the one that has to be right.

**What the Linux install costs is now measured, and the image is not.** Torch comes from the PyTorch
CPU index on Linux and Windows, which took the linux-x86_64 footprint from 4118.0 MB to 188.9 MB by
retiring fifteen `nvidia-*-cu12` wheels and triton that nothing reached — both model call sites pass
`device="cpu"` and no `cuda` or `mps` reference exists in `backend/app`. **The README's 3.4 GB image
figure is now stale and unremeasured**; rebuild and quote the new one here. Windows gained nothing
from the move (113.8 -> 113.7 MB) and macOS is untouched, so the saving is Linux's alone.

**Stopping the backend no longer needs a signal.** The shell POSTs `/setup/shutdown` with a
per-launch secret and signals only what does not answer, so `lifespan`'s drain runs on a host that
has no SIGTERM. It runs on macOS too, because a path taken only where nobody can test it is a path
nobody tests. What accepts is deliberately not also signalled: a second SIGTERM while uvicorn is
unwinding sets its `force_exit` and abandons the drain.

**A process tree is a Job Object on Windows, and the shell now kills one either way.** Windows has
no process group a GUI binary can reach: console control events need a console shared with the
target, and the shell is `windows_subsystem = "windows"`. Each child gets its own job with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, so Python, Ollama and the model runners die when the last
handle closes — including on a crash or a force-quit, the case no shutdown hook covers. The polite
request above is the normal path; the job is the net under it. There is no polite signal there, so
`request_stop` terminates rather than waiting out a grace period that could only end in the same
call, which is why the backend must be asked over HTTP first.

**The platform half is its own crate, `src-tauri/host`, because the shell cannot be compiled for
Windows here.** `tauri-build` needs a resource compiler macOS does not have, so a `#[cfg(windows)]`
block inside `luminary-desktop` is invisible to every developer machine. `luminary-host` has no
Tauri dependency, and `cargo clippy --target x86_64-pc-windows-msvc -p luminary-host` runs anywhere
— it is part of `make desktop-test`. Keep it that way: a Windows branch only CI can see is a branch
nobody reads before pushing.

**`desktop-shell-windows` executes the mechanism, it does not merely compile it, and it has now
run green.** The job runs `cargo test --workspace` on `windows-latest`, and `host/tests/tree.rs`
spawns a child that spawns a grandchild and asserts the grandchild dies with the tree — the defect
the job object exists to prevent, and one `cargo check` could never see. The same tests run on
macOS against process groups. The job shipped in the same commit as the code that makes it pass,
and its first three runs found real defects rather than passing by luck: a `RunEvent` variant that
does not exist off macOS, a test that could only pass on one platform, and a race in the test
harness itself — it read the grandchild's pid, which blocks until the leader has spawned it,
*before* calling `adopt`, so on Windows the grandchild was provably born before it could have
joined the job. `covers_descendants()` was true throughout; the job was never the problem.

**The rest of the platform seams moved with it.** `stage.rs` and `total_memory_gb` had `statvfs` and
`sysctlbyname` hardcoded; `main.rs` read a signal number through `ExitStatusExt`. `base_env` cleared
the environment and added back `HOME` — on Windows CPython does not start without `SystemRoot`, and
`PATH` is `;`-separated. The log had no directory at all there (`%LOCALAPPDATA%\Luminary\Logs`
now), and `report.rs` scrubbed only `HOME`, so every Windows bug report would have carried
`C:\Users\<their name>` in every path unredacted.

**The Windows setup packs and installs silently; the `.deb` installs and opens; the AppImage still does not build.**
`desktop-installers.yml` stages a Windows and a Linux tree through `scripts/desktop/`, builds a
per-user NSIS `-setup.exe`, an AppImage and a `.deb`, installs each and waits for the shell's `ready`
line (`verify_installed.sh`). Decided: NSIS over `.msi` (no admin prompt; `.msi` only if managed
deployment is asked for), unsigned for now (SmartScreen warns). **The Windows stage was 2.28 GB and
makensis fails past ~2 GB**, so this rung carries `lighter-install-plan.md`. CUDA has since left the
installer: it was 629 MB of that stage, Vulkan already serves every GPU vendor, and NVIDIA owners
fetch the faster runner from `/setup/components` afterwards. That required moving the engine to
`DATA_DIR` first -- Ollama resolves its runners from its own executable path with no environment
override, so a downloaded runner has nowhere else to land. The encoder port to ONNX Runtime is now
conditional on x86 numbers that do not exist yet; it is headroom, not the unblock.

**Run `35059810356` is the first that put it through `desktop-installers.yml`, and the ceiling is
cleared.** The Windows stage measured 1610 MB against the 1900 MB budget in `scripts/desktop/lib.sh`,
makensis packed a 298.6 MB `-setup.exe`, and `/S` installed it; the staged engine served
`/api/generate` with `libdirs=ollama`, so runner discovery follows the stage. The `.deb` (653.6 MB)
installed and opened. Two things came back red and neither is the design: linuxdeploy refuses
pillow's vendored `libfreetype`, whose `libpng16-*.so` is reachable only through the RPATH auditwheel
records on the extension module and not on the library itself, and the Windows `Open the installed
app` step died inside its own `find` before it could launch anything, printing nothing. **Both are
fixed and confirmed on run `35080491067`**: Windows (all 17 steps, including "Open the installed
app") and Linux (all 19, including building and opening the AppImage) are both green, and the
Linux job's new shipped-library resolution check reported a real, non-zero edge count (23
libraries, 33 shipped dependencies, all resolving) rather than a check with nothing to fail.
`host_support.py` now splits `has_nvidia_accelerator()` from `_has_amd_accelerator()` --
`_WINDOWS_DRIVER_DLLS` used to hold both vendors' DLLs and `/dev/kfd` is AMD's, not NVIDIA's -- and
`components.catalogue()` calls the NVIDIA-only probe before offering the CUDA runner, so an AMD or
CPU-only host with a staged engine source never sees a download it cannot use. The GPU paths ran on
a real T4 (AWS g4dn.xlarge, Ubuntu 22.04, the run `35080491067` `.deb`, driver 595-open): Vulkan
served out of the box, `cuda_runner` was offered and installed, CUDA took over with 25/25 layers
offloaded, and a first run with the network blocked reached ready on CUDA. Measured on
`qwen2.5:0.5b` only, over HTTP and the log, never through the UI. The first CUDA generation took
~85s against 0.5s warm, and how that splits between model load and runner start is unmeasured; a
first run that looks hung for a minute and a half is a UX defect if it holds on a real model.

**A real Windows first run found two defects CI passed, both fixed.** On an AWS g4dn.xlarge
(Windows Server 2022, 16 GiB, run `35569901354` installer), the silent `/S` install put 38,269 files
into `%LOCALAPPDATA%\Luminary` in under three minutes, bootstrapped WebView2, and reached `ready` 14s
after launch. Then the UI failed every request and every ingest failed:

- Git Bash rewrites a `/`-leading environment value on its way to a native exe, so the SPA was built
  with `C:/Program Files/Git/api` as its API base. `stage_payload.sh` excludes `VITE_API_BASE` from
  the conversion and fails the build if a drive-letter base is baked in (`977d5397`).
- `base_env` cleared `USERNAME`; `getpass.getuser()` has no fallback on Windows and torch calls it
  while importing `torch._dynamo`, so every embed failed and each retry died on "Artifact of
  type=precompile already registered" (`0313221f`).

Both are verified in the installed app: welcome screen, embedding warmup, a `.txt` ingested and found
by search. **`verify_installed.sh` waits only for the shell's `ready` line, which is why neither was
caught**; it should reach the API through the SPA's base and ingest one document.

The same run closed or narrowed the rest:

- **#139 verified on Windows**: 16,864,800,768 bytes of RAM, `host-support` answers `supported`.
  Not re-run on the 16 GiB Linux box that reported it.
- **#24 on Windows**: done except a long username. The deepest installed path is 200 characters
  under `Administrator`, so a 20-character name reaches 207 of 260; computed, not installed.
  Force-killing the shell took Ollama and the backend with it, so the Job Object holds on a real
  install. Linux hardware not run.
- **#99 on Windows**: `render_page` works through WebView2 (vercel.com/blog 22.6s, a Wikipedia
  article 4.0s, both returning the rendered document). Neither page needed script to show its
  content, so the case the feature exists for is not yet demonstrated. WebKitGTK not run.
- **The T4 was unusable to the app.** The data-center driver runs in TCC mode, which Vulkan cannot
  see, and `nvidia-smi -dm 0` is not supported there; Ollama reported 0 B VRAM and ran on the CPU.
  A consumer GeForce card in WDDM mode is the test Windows GPU support still needs.

**`make smoke` on Windows is not green, and the gate as written cannot run.** The bundled app is
public mode on an ephemeral port and every smoke script hardcodes `localhost:7820` in full mode, so
the run used a from-source full-mode backend against the app's own Ollama. On a rerun of the first
pass's failures, what still fails is the host, not the app:

| Class | Scripts | Cause |
|---|---|---|
| CPU-only LLM | S62, S63, S77 | TTFT 351s, 625s per answer |
| `/search` timeouts | S212 | see below |

The harness failures from that run are fixed. Thirteen scripts ran `npx`/`tsc`/`vitest`, which a
machine with only the installed app does not have; `make ci` already builds, type-checks and tests
the frontend, so smoke no longer does, and `check_smoke_paths.py` rejects a script that runs the
frontend toolchain. S121 uploads a real empty file rather than `/dev/null`, and S245 no longer uses
`mktemp -t`. **S212's numbers are not retrieval
measurements.** `run_eval.search_chunks` turns a failed request into an empty list, which scores as a
miss: `book_alice` read HR@5 0.0000 with the backend busy, and passed once it was idle, while
`book_time_machine` then read 0.35 with 22 of 40 searches past the 30s timeout. Why some searches exceed 30s on a 4-vCPU host is unmeasured.

The harness side is fixed: every script reads `LUMINARY_BASE_URL`, skips a full-only surface on a
public server, and writes temp files under `SMOKE_TMP` (`scripts/smoke/lib.sh`, enforced by
`check_smoke_paths.py`); a failed eval search now fails the run (I-32). On macOS, full mode, with
`SMOKE_OFFLINE=1` and the backend holding no non-local connection (I-57, I-18), 170 of 177 passed
and none failed on `d1520e5a` once #140, #141 and #142 were fixed. A skip now exits as a skip:
seventeen scripts had printed SKIP and counted as passes. Of the seven skips, S122 needs the
network, and S110-S112 and S132-S134 find no document because they run before any script ingests
one, so they exercise nothing on a fresh library. A script with no verdict after 30 minutes is
killed and failed, and a silent `set -e` exit names its command.

**`verify_installed.sh` ingests a document through each installed build, and has run green.** Run
`35654900886`: the AppImage and the `.deb` each ingested and found the document by vector search in
4s and 3s, the Windows setup in 8s.

What remains open:

- `make smoke` green on Windows against the bundled app.
- #24 and #99 on Linux hardware; #24 under a 20-character Windows username.

**A Kuzu lock cannot go stale is a POSIX statement.** `flock` is advisory and released by the kernel
when the holder dies, which is why this repo forbids a lockfile or any lock-clearing logic. Windows
locks are mandatory and a handle can outlive an abrupt termination, so the same relaunch raises
`PermissionError: [WinError 32]`. Do not port the graph store on that argument alone — 2,583 lines
and 163 Cypher statements across 26 node and edge types. The retrieval arm is now measured (0.15.0,
below): it contributes nothing, so the port-or-delete question is about the store's other readers.

**On a host that cannot run a local model, the chosen mode decides what runs, and the app says so.**
Local, Hybrid and Cloud are one stored setting, asked once at first launch for every install path and
changed in Settings; both render `lib/engineModes.ts`, and nothing switches the mode on the user's
behalf. Hybrid keeps enrichment local, so on such a host it does not run: `llm_routing.refusal` is
asked before background work, the enrichment worker records the job skipped rather than failed or
empty, ingest skips summaries and tags, and the routing table and host banner name what is not run.
Cloud mode is the opt-in that runs enrichment with the user's key and sends document sections to the
provider; a mode change that lifts the refusal re-queues skipped jobs and repairs missing summaries.
Not repaired by a switch: tags (the "retag all" action does it) and the domain and register
classification written at ingest. Guarded by `tests/test_engine_mode_on_unsupported_host.py`.

**What does not move on any platform.** Indexing, retrieval, transcription, entity extraction and the
learner record stay local in every mode and are reported as such by `llm_routing.routing_report`. A
hosted embedder is a full re-embed behind I-9, not a setting, and routing extraction or reranking to a
provider would put document text rather than a question on the wire.

**Still open in Phase I.** 0.13.0 shipped with the Linux T4 first run, `make ci`, `verify-dock`
and `verify-citation` green. Not yet run:

- A first run of the installer on a real Windows machine past what CI does (install, ingest,
  search in `desktop-installers.yml`), and `make smoke` there.
- `make smoke` against the bundled macOS app, and the DMG on a cleared data directory.
- #110: a route chunk can fail to load in the packaged app, cause unknown. The bundled backend logs
  no request status or latency, so the next occurrence could not be diagnosed either. That logging
  comes first.

Defects that were written here have moved to the tracker: `eval-summary` scoring a stored summary
(#154), the Windows proxy for model pulls (#155) and split GPU/CPU offload (#156) belong to this
phase. The false-premise answer (#158), Wikipedia `[edit]` links (#159), flashcard floors (#160)
and YouTube verification (#162) belong to 0.15.0. Three instrument defects listed here were fixed
on `master` before the move: `eval-ingest` re-resolves a document by filename (#143), atomicity is
structural (`is_atomic`), and a judge verdict outside its enum is excluded rather than crashing
the run.

**0.13.2: one-command installs on Windows and Linux** (on `feat/windows-linux-release`). The aim
for 1.0 is reach: any recent Windows or Linux machine either runs well or is told before the
download that it cannot, as an Intel Mac is today, and pointed at a cloud key or the hosted version.

| Item | Status |
|---|---|
| `get-luminary.sh` / `.ps1` install the latest release in one command | built, CI installs through them |
| SIGTERM drains the process tree on Linux and macOS; an AppImage without FUSE ends with its runtime | built |
| Off Apple Silicon the default text model is `qwen3.5:4b` whatever the host holds; other models are the user's pick in Settings | built |
| The one-command installers refuse before downloading where `host_support.local_inference_support` would, with its message, and offer to continue for reading, search and notes (`LUMINARY_INSTALL_ANYWAY=1` without asking); `test_get_luminary_script.py` fails if they disagree | built |
| A release job attaches the Windows setup, `.deb`, AppImage and their `.sha256` files; README carries the one-liners | built: `desktop-installers.yml` `publish` attached all four to the `v0.13.2` prerelease; the README leads with the one-liners, which resolve the latest release; merged to `master` in 0.13.8 |
| Uninstall deletes only files Luminary wrote; the library, models and anything unrecognised are listed with the command to delete them | built, CI uninstalls on Windows and Linux with a planted foreign file |
| An installed Ollama is reported, and its models the app knows are reused after a digest check, never written to | built: the Windows installer job and `test_get_luminary_script.py` reuse a planted model; not run against a real Ollama install |
| One timing script over the installed app: doc ingest, web-article ingest, Ask idle and while a later doc ingests, flashcards, teach-back, store sizes, on `qwen3.5:4b`; its baseline is the M3 Pro | built: `scripts/time_flows.py`; M3 Pro baseline below |
| Hard limits checked before any cloud run: installer size budget, path length, driver mode | checked, below |

**Cloud runs are on hold at the user's cap.** ~US$15 was spent on the 0.13.x AWS runs without a
usable number; the ceiling is US$20, so the two-box `g6.2xlarge` plan (which needed a 16-vCPU
increase) is off, and the pending increase is left unused. Real-hardware Windows validation comes
from a friend's machine running the rc prerelease. If a controlled GPU timing is still wanted
inside the cap, one `g6.xlarge` (4 vCPU, single L4) fits the existing 4-vCPU quota with no
increase, Windows only, terminated the same session; it is not launched without the user asking.
An L4 is the laptop class these hosts are (Ada, ~300GB/s against a laptop's 192-256), but its 4
vCPUs make CPU-bound ingest read slow, and `g4dn`'s T4 ran Windows on the CPU.

**Parity bar: every timing within 1.5x of the M3 Pro** (`time_flows.py compare` exits 2 past it).
It also refuses a report whose per-core load reached 4.0 during timing: past that the number is
the machine, not the app, and must be rerun on a quiet host.

**Hard limits for the release and the cloud runs** (0.13.1 installer run `35927916664`, the
`personal` account in `ap-southeast-2`):

| Limit | Ceiling | Measured |
|---|---|---|
| NSIS pack size | ~2048MB; `verify_stage.sh` fails at 1900MB | Windows stage 1616MB |
| Windows MAX_PATH | 260, less ~60 for the install root; `verify_stage.sh` fails past 190 | longest 165 (Linux 154) |
| GitHub release asset | 2GiB per file | largest 667MB (`.deb`); AppImage 619MB, setup 301MB |
| On-demand G-instance vCPU quota | 4 | a 16-vCPU increase was requested 2026-09-24 but is not pursued (cost cap); within 4 vCPUs a single `g6.xlarge` (one L4) is the only GPU box |
| Root volume | Ubuntu AMI 8GB, Windows 30GB by default | the app needs ~9GB beyond the OS and driver (install 2.1GB, CUDA 0.6GB, `qwen3.5:4b` 3.4GB, encoders 1.5GB, installer 0.7GB): launch Linux with 40GB, Windows with 60GB |
| GPU in WDDM on Windows | AWS's GRID driver (596.86 for Server 2022) | with the stock driver the 0.13.0 `g4dn` Windows box ran on the CPU; GRID on the L4 not yet tried, ten-minute cut-off above |

**M3 Pro baseline** (36GB, `qwen3.5:4b` pinned in Settings, `scripts/time_flows.py` driven by
`scripts/time_flows.plan.json`: a book `.txt`, a `.pdf`, and a Wikipedia URL, each into its own
fresh empty library; two runs). Load stayed under 0.5/core in both runs, well under the `compare`
refuse guard (4.0/core).

| Flow | Doc | Run 1 | Run 2 |
|---|---|---|---|
| Upload to ingest `complete` | book (`.txt`) | 96.9s | 100.0s |
| | book (`.pdf`) | 108.3s | 99.2s |
| | web article | 90.9s | 82.2s |
| Background work settled | book (`.txt`) | 451s | 414s |
| | book (`.pdf`) | 1360s | 1320s |
| | web article | 479s | 482s |
| Ask, full answer (3 Qs) | book (`.txt`) | 14.1 / 16.8 / 18.0s | 15.5 / 13.4 / 21.7s |
| | book (`.pdf`) | 13.5 / 20.2 / 31.0s | 12.0 / 19.5 / 28.7s |
| Ask while a later doc ingests (3 Qs) | book (`.pdf`) | 17.6 / 11.9 / 27.7s | 18.1 / 23.8 / 45.2s |
| Ask on the web article (1 Q) | web article | 119.3s | 16.3s |
| 5 flashcards, fast mode | book (`.txt`) | 23.5s | 24.7s |
| 5 flashcards, slow (a card refilled) | book (`.txt`) | 36.3s | 32.7s |
| Teach-back evaluation | book (`.txt`) | 4.2s | 5.7s |
| Store size, SQLite / vectors | book (`.txt`) | 6.4 / 2.0 MB | 6.3 / 2.0 MB |
| | book (`.pdf`) | 9.9 / 3.9 MB | 9.9 / 3.9 MB |
| | web article | 11.2 / 5.1 MB | 11.3 / 5.1 MB |

`time_flows.py` times the reader flows only after background work has settled: section summaries
run for minutes after `complete` (the `.pdf`'s take about 22). Card time is bimodal — about 24s, or
33-40s when a card fails the grounding check and is refilled — so hosts are compared mode to mode,
never averaged; the `.pdf` deck spiked once to 100s, so the slow mode has a long tail. **The single
web-article Ask is not yet a trusted number**: the two runs gave 119s and 16s, and 16s matches every
other Ask, so 119s is an outlier that more samples must confirm or discard before the figure gates
anything. The only non-local traffic in either run was to the Wikipedia host the plan ingests; no
reference-link checks fired (I-58).

**Not in 0.13.2.** Intel and AMD integrated graphics are refused as `no_accelerator`, though Ollama
serves them through Vulkan. That covers most current Windows laptops, and whether to admit them is
decided in 0.13.3 once one has been timed on `qwen3.5:4b`; AWS has no such machine. Code signing
(SmartScreen warns) is not in it either — see below.

**0.13.4: company networks.** A company laptop behind a TLS-inspecting proxy failed every model
download (I-59). Verified on AWS Windows Server 2022, m6i.xlarge with no GPU, behind mitmproxy with
its CA in the machine store and set as the Windows proxy: 0.13.3 reproduced the laptop's screen;
0.13.4 over it downloaded the embedder, installed both optional encoders, ingested a web article and
an arXiv PDF by URL, reached OpenAI in Hybrid mode, opened the problem report in Notepad, and kept
loopback off the proxy. Smoke there: 120 pass, 0 fail, 57 skip. Open: Ollama ignores the Windows
system proxy, and PAC files are not read (#155).

**0.13.5–0.13.7: a driver is not a usable card (I-60).** Verified on AWS g4dn.xlarge, Windows Server
2022, T4 with the AWS GRID driver (WDDM), no proxy, installed by the one-command installer. Card
enabled: the chat-model install loaded it at once, Ollama held all 3.44 GB on the T4 through Vulkan
(17s warm), and with the CUDA runner through CUDA; three documents ingested (a Wikipedia article, 645
chunks; an arXiv PDF, 81; a text file, 11), questions answered in 5-14s with citations, 2 of 5 cards
survived the grounding check, a review rescheduled, teach-back scored 98 right and 0 wrong. Card
disabled with the driver left on disk: warm-up measured 0 B on the card, refused with `gpu_unused`,
unloaded the model and showed the banner in the same session; questions, cards and teach-back were
refused with the key message, while reading, search, reviews and a new ingest worked, and Hybrid with
a bad key said so. Installing the CUDA runner cleared the verdict and the next launch measured again.
Open: a split GPU/CPU offload is not refused, and no consumer laptop GPU, integrated graphics or
Linux GPU host has been measured (#156).

**0.13.8: private mode with no connection (I-61).** A desktop demo with Wi-Fi off showed an empty
library with nothing in the backend log: TanStack Query paused every request after the webview's
`offline` event. Verified in headless Chromium against the installed 0.13.1 UI (empty) and the fix
(14 documents), and on a backend whose outbound traffic went to a refusing proxy: ingest, search,
Ask with a citation, cards, review, teach-back, notes and summary, with zero outbound attempts. The
macOS app itself was not run with Wi-Fi off.

**0.13.9: the AppImage on current distributions (I-62).** The AppImage opened a blank window on
Fedora 44 and Bluefin. It bundled an old libwayland that the host's graphics drivers could not
load against. Graphics libraries now always come from the system, and CI opens the AppImage under
Wayland against the newest Fedora, Arch, Ubuntu and Debian drivers (PR #152).

**Signing.** The installers are unsigned, so Windows SmartScreen shows "unknown publisher"
(click More info -> Run anyway). The free route is SignPath Foundation, which signs OSS builds at
no cost; the repo qualifies (public, Apache-2.0). The application is the owner's to submit (it needs
a 2FA'd GitHub account); once approved, a signing step in the Windows job submits the built `.exe`
and gets it back signed, publisher "SignPath Foundation". macOS has no free path (Apple Developer,
US$99/yr), so it is out of scope here. Linux needs none: the `.deb`/AppImage ship `.sha256` files
the wrappers verify.

**Seams kept for the hosted version and mobile.** The host verdict has one owner,
`host_support.py`, served over HTTP, and the installers copy it under test. The default model lives
in `model_registry.py`. The engine is a setting (`llm_mode`) behind LiteLLM, and embedding,
retrieval and the learner record never move with it. Desktop-only code stays in `luminary-host` and
`src-tauri`, so the same backend can serve from a server.

**Exit gate.** First run completes with no terminal on a Windows and a Linux machine that has never
seen Luminary; each host's verdict names the accelerator it actually has, proven by a platform-pinned
test and a Windows CI job; `make smoke` green on Windows and against the bundled macOS app; #24,
#99, #110, #154, #155 and #156 closed. Then Checkpoint A.

### 3. Gates you can believe — 0.14.0

`make ci` and `make smoke` green together, with nothing quarantined to keep them so. Today that takes
23 `pytest.mark.unstable` markers across 14 files (#50). Local green is necessary and not
sufficient: GLiNER memory pressure has produced GitHub-only failures that no local run reproduces.

What the gate cannot pass without:

- **#50**: the quarantine itself, and 111 duplicated DB fixtures. Timing policies were tried on it and
  failed; the durable fix is per-site.
- **#101**: the entity-extraction test doubles take the wrong signature and always raise, so no
  ingestion test exercises extraction or its Kuzu writes. The three `integration_http` tests are
  skipped on GitHub, so upload-to-complete ingestion never runs where a release is gated.
- **#88**: the clustering holder was fixed in 0.11.0, but the reproduction that found it (smoke under
  60 concurrent `/qa` calls) has not been re-run. It closes on 0 lock errors under that load.
- **#157**: the lock-holder report built on an unmerged branch. Without it, a non-zero result on #88
  names the victim, not the holder.

This rung exists to shrink as the ladder runs. It grows only if a later rung breaks the
no-new-quarantine rule, and that is the signal to move it back up.

### 4. Stores that agree, output you can measure — 0.15.0

A failed graph write is lost, and SQLite and Kuzu diverge with nothing reconciling them (#65). Entity
ingest samples 2.4% of a long book, and reindex disagrees with ingest (#63). The md/epub/docx/txt paths
are unmeasured, and audio ingested before 0.7.5 has no sections (#97). The parent-section duplication
#97 also named is fixed.

**What a user receives is measured before it is a default.** Two shipped behaviours change the answer
with no quality number behind them: the slow-host context budget halves the passages, and note
search's semantic arm is never scored on a query with no lexical overlap (#100). Suggested questions
are generated from section summaries rather than text, so they presuppose framings the document never
makes, and the ungrounded answer that follows renders like a grounded one (#66). The same bar covers
Ask on a false premise (#158), web chunk hygiene (#159) and the flashcard floors (#160).

**Query-time graph expansion buys no retrieval quality.** `run_eval.py --ablation`, 2026-09-21, dev
library, GLiNER held resident and the arms confirmed to diverge before and after each dataset. On the
shipped funnel (rrf+rerank), HR@5 is identical with and without expansion on all five sets (book 40,
paper 40, legal/play/study 60 rows), and MRR moves by at most 0.003 in both directions, which is less
than one question. Unreranked, no set moves by more than one question in either direction. Measured:
the `_graph_expand` alias tokens on `/search`. Not measured: the chat `graph` node, which routes
relationship questions to Kuzu and not to `/search`.

**Expansion is also dormant in the shipped app.** `_graph_expand` skips when GLiNER is not loaded
(`retriever_strategies.py`). Only startup warmup and ingestion load it, and the reaper releases it
after `NER_IDLE_RELEASE_SECONDS=180`. A user's search therefore expands only in the three minutes
after launch or an ingest. Given the ablation, the fix is to remove expansion from `/search`, not to
keep GLiNER resident for it.

**The Kuzu port-or-delete decision is made here.** 28 modules read the graph store: the chat `graph`
node, graph flashcards, concepts, mastery, study paths and prerequisite extraction among them.
Retiring expansion removes one reader. The decision for the rest weighs what those features deliver
against #65, #161 (`RELATED_TO` empty library-wide, and self-pairs left by pre-0.11.0 ingests), and the
Windows lock (0.13.x above). It also settles 0.17.0's scope, because whatever store survives needs a
library scope.

**The last of the document-model work belongs here.** `form`, `domain` and `register` are written at
ingest by `_persist_classification`, and `DocumentProfile` owns the policy. What remains is retiring
the legacy `content_type` projection and `is_technical`. It is a migration, and migrations get more
expensive with every user.

YouTube ingest is re-verified on every platform (#162) before the checkpoint's manual gate relies on
it. Then Checkpoint B: the app is stable enough that the next three rungs open it to the network.

### 5. Device auth and pairing — 0.16.0

**The backend is unauthenticated on localhost, and CSRF is deliberately open.** Any page in any tab
can already POST to :7820. This rung closes that, because authentication is what makes it possible.
The gate is that an unpaired origin or a revoked device is refused, proven by a test that fails when
pairing is removed.

**Pairing is per device, not per origin.** A one-time code shown by the desktop app is exchanged for a
named, revocable token that is stored hashed. 0.18.0's server, 0.20.0's phone and 0.21.0's extension
all reuse it; an origin allowlist would serve the extension and nothing after it. The app's own origin
stays tokenless on loopback, and any other origin needs a token. `TrustedHostMiddleware` in `main.py`
pins loopback against DNS rebinding, and that pin may only widen when authentication is on.

A token resolves to a principal. 0.17.0 hangs the request context off that principal, so the token
shape is decided with the tenant seam in view, not retrofitted to it.

### 6. An architecture that can take tenants — 0.17.0

**Only the seams that are expensive to add once users have data.** There is no tenancy UI and no
billing; hosted multi-tenant is after 1.0 (Deferred). On desktop every seam carries a single value.
Today `models.py` has no owner, tenant or library column, data sits under one global `DATA_DIR`
(`config.py`), and 54 files call `get_settings()`.

| Seam | What it means |
|---|---|
| A library scope on every query | `library_id` on user-owned tables, the LanceDB tables and the graph store (or its 0.15.0 replacement). The migration is additive with a backfill: DDL and backfill in separate revisions (I-23) |
| A request context | `principal` and `library` flow from the auth middleware through services to repos. No repo reads global state to find its data |
| One path resolver | Direct `DATA_DIR` joins go through a resolver that takes the library, so each tenant gets its own root, or later an object store |
| Per-library settings | `get_settings()` splits into process configuration and per-library or per-user preferences (`llm_mode`, keys, model picks). API keys move to storage scoped to the principal |
| Shared-resource audit | Model residency, `MODEL_LOAD_LOCK`, the write-lock watchdog and the background queues, checked for anything that assumes one user. Fairness waits for the hosted work; correctness does not |
| A layer-linter rule | `layer_linter.py` fails when a repo function lacks a library scope. Without it the seam decays |

**The snapshot/restore format and the re-embed rail ship in the same rung.** Moving to a multilingual
embedder regenerates every vector in every library, and 0.x is the last point at which the
compatibility promise is weak enough to absorb that. The argument is about the machinery, not the
model: a resumable, restartable re-embed plus the snapshot format is the same work that library
export, a server restore and the OKF projection need (I-21). It is proven against the current 384-dim
embedder, where a wrong answer costs nothing. #48 (model-change configurability) is the settings side
of the same rail.

### 7. Your own server — 0.18.0

**Luminary on the user's own cloud.** The container is most of it already: `Dockerfile` plus
`LUMINARY_MODE=public` serves the SPA and the API on one port, and a compose volume holds the library.
**What is missing is authentication, and 0.16.0 builds it.** `docker-compose.yml` binds `127.0.0.1`
precisely because there is none. Until this rung ships, reaching the container from elsewhere is a
tunnel the user owns, and the docs say so.

**A server with no GPU is an unsupported host.** `host_support.local_inference_support` answers
`container_without_accelerator` for a CPU-only container, so every local call is refused. Cloud mode
with the user's key is the answer (engine modes, 0.13.x), and this rung's gate proves it builds an
enriched library.

Then Checkpoint C.

### 8. Components separated for mobile — 0.19.0

**Frontend.** 57 raw `fetch(` calls in 32 files still bypass `lib/apiClient.ts` (2026-09-27, excluding
tests); they move onto it first, so the phone has one place to add its token and its cache. Then
`packages/api` (client plus types), `packages/domain` (hooks and state) and `packages/ui` are
extracted, and desktop and mobile become thin shells. `surface-manifest.json` gains a `mobile` mode:
a third mode, not a fork.

**Backend.**

- An incremental change feed for documents and notes.
- Idempotent writes keyed by client ids, which the offline outbox needs.
- A render-ready document endpoint for reading on the phone. Prose is never rebuilt from chunks (I-29).
- Review logs made append-only, so an offline merge replays reviews rather than overwriting FSRS state.

Desktop-only code stays in `luminary-host` and `src-tauri`, as today.

### 9. Topic notes, then mobile reading and note capture — 0.20.0

**Topic notes land first (#173), because dictation on a phone turns every thought into a small
draft.** A topic note is written from several short notes: a summary, then one section per subtopic.
It is not a collection. A collection groups notes; a topic note is new content with a recorded source
for every section. It depends on nothing cloud or mobile, so it can ship before the client.

- **Merge once, then place.** The first merge builds the note. Later drafts go into the section they
  belong to, and existing text is not rewritten unless the user asks. Re-summarising on every
  addition rewords the last rewording until the user's own sentences are gone.
- **A draft inbox.** New notes arrive as drafts, each with a suggested topic and section by embedding
  distance. `clustering_service.py` proposes a new topic when loose drafts match none.
- **Preview, and keep the originals.** Nothing saves until the before/after preview is accepted.
  Source notes are archived, never deleted, and a merge can be undone. Links to a merged note resolve
  to its section.
- **Nothing lost, nothing invented** (`product-integrity.md`). Coverage is structural: a source note
  no section claims fails the merge, as `RefineDroppedContentError` does for a dropped image. The
  summary is checked against its source notes. Dictation fixes show as fixes.

**A Tauri 2 mobile client for reading and notes, the two things done away from a desk.** Ingest and
the models stay on the user's server or desktop. The phone talks to that server or to a paired
desktop, authenticates with 0.16.0's device token, and keeps a local cache of documents plus an outbox
for notes written offline. The outbox drains through 0.19.0's idempotent writes, so a retried note is
never stored twice.

Then Checkpoint D.

### 10. Anki import, capture and mobile review — 0.21.0

**Anki import.** Export already ships: `export_service.py` writes a `.apkg` through genanki for a
collection's deck. There is no import path. The hard part is not the file format. A Luminary card
carries `source_chunk_ids` and a per-card grounding verdict (I-34, I-35), and an imported card has no
passage in the library to point at. Decide what grounding means for a card whose source is elsewhere
(shown as ungrounded, bindable to a document later, or held in a separate lane) before writing a
parser, or the invariant quietly stops meaning anything. FSRS state is the second question: an Anki
deck carries SM-2 scheduling, and `fsrs` v6 state is not the same shape. Importing intervals naively
produces a schedule that looks continuous and is not.

**The capture extension.** A library stays empty when filling it means opening the app and finding the
file. The backend is already HTTP, so an extension needs a POST rather than an architecture: one click
for a page, a PDF, a YouTube video, or a selection with its source. It pairs with 0.16.0's device auth.
A watch folder for the desktop app, Markdown export shaped for Obsidian, and a Zotero read path ship
with it.

**Card review on mobile.** It rides 0.19.0's append-only review log, so a review made offline merges
without discarding one made on the desktop.

The enhancements that were on no rung land here: PDF math as LaTeX (#137), figure-caption quality
(#124), nugget recall for answers (#121), parent-document retrieval (#25), the Hub approximations
(#103) and a copy-link button for notes (#26, a good first issue that can land at any time).

### 11. Multi-language — 0.22.0, conditional

**Measure first.** Embeddings are `BAAI/bge-small-en-v1.5`, 384-dim and English-only, and every stored
chunk, note, image and concept vector lives in that space. GLiNER is already multilingual
(`gliner_multi_pii-v1`), so entity extraction survives a move and retrieval does not. Nobody has
measured how far the current stack degrades on non-English text; that number decides the rung.

**A swap ships only through 0.17.0's rail.** A no-go is an allowed outcome and moves the swap to 1.1.
Interface localisation is separate, seamed and unbuilt: every surface in `surface-manifest.json`
carries `labels: {"en": ...}`.

**Encoders.** fp32 ONNX Runtime for the encoders is a size change rather than a speed one: the same
weights at fp32 measured cosine >= 0.99999982 against the shipped embedder with identical top-10
retrieval, so it is not a re-embed. **A quantized ONNX encoder is**, and stays behind I-9 and the rail.
Replacing only some of `optimum`, `sentence-transformers` and `gliner` *increases* the bundle, since
each declares torch unconditionally, so a port replaces all three. The encoders are not the latency
bottleneck: a slow host's ~121s question is the 4B model at ~6 tok/s, served by Ollama. For an
accelerated encoder, `onnxruntime-directml` is the broadest Windows execution provider (NVIDIA, AMD,
Intel Arc and Intel NPUs through one wheel), but it publishes `win_amd64` only, so a Snapdragon NPU
needs a different provider.

### 12. The release — 1.0.0-rc, then 1.0.0

The candidate is Checkpoint E: the checkpoint gate, plus zero open `bug` issues, plus every rung's exit
gate green together on one build. 1.0.0 is that build with no new features.

### Bugs to 1.0

- **One GitHub milestone per rung** (`0.13.x` to `0.22.0`, then `1.0.0`). Every open issue carries
  one; the table above is the mapping.
- **A new bug is triaged when filed** to the current rung or the next one.
- **A checkpoint is not tagged while a `bug` issue is milestoned to its phase or an earlier one.**
- **A defect found while writing this file becomes an issue**, and the prose keeps only its link
  (see "Adding to this file").
- Each rung's row lists its issues, and an issue appears on exactly one row.

### Code quality to 1.0

**Debt is paid down along the ladder, not in a phase of its own.** Each rung's first PR refactors
what that rung is about to change, with no behaviour change, `make ci` green before and after, and
existing tests as the net (characterization tests first where they are thin). Nothing is split for
size alone. **Work lands in batches of a few PRs, and each batch stops for a manual test
pass** on the app before the next one starts: the suite cannot see what a refactor did to a
screen, and a regression found after five more PRs is five times harder to place. **Ratchets** stop new debt landing meanwhile: each check is baselined on today's numbers
in `make ci` and may only shrink, as `KNOWN_VIOLATIONS` already does in `layer_linter.py`.

Measured 2026-09-27 on `master` (`5e8cb41e`). The targets follow the usual external bars: McCabe's
10 per function (NIST SP 500-235), and the SonarQube default quality gate (maintainability A,
duplication ≤ 3%, coverage ≥ 80% on new code).

| Metric | Tool | Now | 1.0 target |
|---|---|---|---|
| Functions over 120 lines | `ast` | 57 of 2,250 | 0. Exempt: `db_init.create_all_tables` (787, frozen by I-23) |
| Cyclomatic complexity over 20 | `radon cc` | 58 (worst: `qa.stream_answer` 93, `synthesize_node` 71, `flashcard_generators.generate` 61) | 0 |
| Cyclomatic complexity over 10 | `radon cc` | 231 of 2,128 (10.9%) | under 5% |
| Maintainability index below A | `radon mi` | 6 files: `routers/study.py`, `routers/documents.py`, `routers/evals.py`, `flashcard_generators.py`, `parser.py`, `qa.py` | 0 |
| SQL outside `repos/` | `grep` for `select(` and `session.execute` | 310 in 16 routers, 644 in 75 services (131 in repos) | 0 in routers by 0.17; services by 1.0 |
| Duplicated lines | `jscpd`, 8-line clones | 1.11% (96 clones) | ≤ 3%, held |
| Dead Python | `vulture` ≥ 80% confidence, plus unreferenced symbols | 8 unused imports/variables, ~11 unused functions/classes | 0 |
| Dead TypeScript | `knip` | 12 unused files, 29 unused exports, 77 unused exported types, 1 unused dependency | 0 files, 0 dependencies |
| Test coverage | `pytest --cov`, `vitest --coverage` | **not measured** (the cloud container cannot install torch) | Floor set in 0.14 from the measured number; ≥ 80% on changed lines |
| Quarantined / skipped tests | markers | 23 `unstable`, 16 `skip` | 0 `unstable`; every `skip` names what re-enables it |

**Tests, evals and smoke are code, and carry debt too.** Test code (84,366 lines in 350 files) now
outweighs the app (~80,000). There are 132 locally defined DB fixtures (#50 counted 111).
Smoke is 158 scripts, and every one calls the server: the 19 that never did (in-process `app.`
imports, eval-harness unit checks, source greps) are now `test_eval_harness_wiring.py` and
`test_prompt_and_config_contracts.py`, or were deleted where pytest already covered them.
Eval runners are 12 scripts and 7,977
lines with their own copies of manifest, search and history plumbing.

| Rung | Refactor, as the rung's first PR |
|---|---|
| 0.14 | The ratchets above in `make ci`. Move `qa.stream_answer` to `runtime/`, which empties `KNOWN_VIOLATIONS`. One shared DB fixture (#50). The 11 in-process smoke scripts become pytest tests, or are deleted where pytest already covers them. Measure coverage and set its floor |
| 0.15 | Split `summarizer.py` into `summary_prompts.py` and `summary_assembly.py` (both pure), `repos/summary_repo.py` (its 24 queries), and `library_summary.py` (the library-wide half, with its Kuzu read). The same prep for the other `content_type`/`is_technical` readers the retirement touches (37 files), starting with `flashcard_generators.generate` and `parser._parse_pdf`. Eval runners share one `evals/lib` path for manifest, search and history |
| 0.16–0.17 | Repos extracted from `routers/study.py` (103 queries) and `routers/documents.py` (42), then from the services with the most direct SQL, before `library_id` lands, so the scope is added in one place. `get_collection_study_dashboard` and `list_documents` are split on the way. The 53 `DATA_DIR` joins go through the path resolver |
| 0.18 | `main.lifespan` (300 lines) becomes named startup phases |
| 0.19 | `fetch` onto `apiClient`, then `DocumentReader` (1,946 lines), `PDFViewer`, `Notes` and `ChatConversation` split into `packages/domain` hooks and `packages/ui` views |
| 1.0-rc | Every target above met, or its exemption stated here with the reason |

## Deferred — decided, not scheduled

- **Sync through storage the user controls** (iCloud Drive, OneDrive, Dropbox, Google Drive) —
  after 1.0; in 1.0 the phone syncs through the user's server. The live stores cannot be what syncs:
  SQLite with WAL, LanceDB and Kuzu are all mid-write-sensitive, and a daemon copying a `-wal` or a
  Kuzu directory mid-write produces a corrupt library on the other machine. What syncs is 0.17.0's
  snapshot format, with the live stores rebuilt from it. Two machines that both studied offline have
  divergent FSRS state, and last-writer-wins silently discards a review session.
- **Hosted multi-tenant, the paid tier** — after 1.0. 0.17.0 builds the seams it needs; fairness
  across tenants, billing and a tenancy UI are its own work.

- **A serving width of 4, for a machine that asks for it.** Every install path sizes
  `OLLAMA_NUM_PARALLEL` from physical RAM and caps the automatic value at 2 (I-31): `performance`
  is reachable from RAM now, so a 4 keyed to that profile would hand every 32GB machine a width
  the measured table never reached — it stops at two callers, 97.7 tok/s. Four is still reachable
  by writing `OLLAMA_NUM_PARALLEL=4` into `.env`. What does not exist is the path that tells a
  profile a human chose from one sized from RAM: `memory_profile.profile_is_explicit()` answers it
  for the backend and no installer reads it, so an explicit `LUMINARY_PROFILE=performance` cannot
  re-enable 4 on its own. Worth building only together with a measurement at four slots, which
  nobody has taken.

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
- **Routing embedding, reranking or entity extraction to a cloud provider** — rejected 2026-09-10,
  proposed as the way to make legacy CPU laptops usable. Two disqualifying facts. A hosted embedder
  is a different vector space, so it is a full re-embed behind I-21's rail and a migration rather
  than a setting (I-9); `llm_routing.routing_report` reports indexing as fixed-local for that reason.
  And it inverts the claim the product sells: today one question and its packed passages leave the
  machine, while this puts every chunk of every document — and, for extraction, whole document text —
  on the wire. Synthesis is routable; the index is not. BYOK for **generation** on a host that cannot
  run a model is the supported answer and ships in 0.13.0.
- **Two Ollama services** — rejected on a single-GPU/8GB machine. See I-31: enrichment cost is
  call count, not concurrency, so the lever is fewer calls, never more parallelism.

## Adding to this file

An entry is warranted when a **feature** is decided but not done, or rejected and likely to be
re-proposed. When one ships, delete its entry and add a row to Shipped naming the doc that now
carries the contract.

**A bug is an issue, not a roadmap item** — that rule was already here, and this file drifted
from it anyway. The tell is an entry that names a `file:line` and a symptom rather than a
capability: that is a defect with good evidence, and the evidence belongs in the tracker where
someone can close it. If an entry could be titled "X is broken", it is an issue.
