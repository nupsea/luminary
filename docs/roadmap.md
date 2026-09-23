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
| Frontend lint as a CI gate, `apiClient` used everywhere | `Makefile` `ci` target, `frontend/eslint.config.js` |
| Six-layer architecture, stores, surface modes | `architecture.md` |
| The 43 hard invariants | `invariants.md` |
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
planning unit.

Rung numbers are ordering, not commitments. Several will split once scoped.

**1.0 is a production-grade local-first app on every host, reachable from the user's other
devices.** Stability and architecture rungs come before feature rungs; a feature that only
decorates the first run waits until after 1.0. Your own server, sync, mobile, Anki import and the
encoder work are on the ladder, not after it.

Feature rungs land on a suite with a live quarantine, so **a rung ships its smoke scripts with its
endpoints (`CLAUDE.md`) and adds nothing to the quarantine**. The quarantine grew once — 22 to 23 markers
on 2026-09-18 (`fcfb4e5d`, a `POST /notes` case in `test_S201.py`) — so the gates rung moved up
the ladder, ahead of capture, as this rule said it would.

Every rung that lands after 0.13.0 adds surface to a Windows and a Linux build that already work;
every rung that lands before it adds surface to fix later, on platforms no CI runner exercises.

**One authentication mechanism, built in 0.16.0, serves capture, your own server and mobile.**
Building it per consumer produces three trust models that disagree.

The ladder runs in five phases. The last rung of each phase is a **checkpoint release** (below):
the whole product is measured on one build, not only the rung that just landed. The issues listed
against a rung are the ones its exit gate cannot pass without.

| Phase | Rung | Theme | Issues | Exit gate |
|---|---|---|---|---|
| — | 0.10.0 | Smart Hybrid, and the privacy receipt — **shipped** | | Time to first token measured on both arms from a cold install and reported as a pair; a test proves that only the question and its packed passages leave the machine |
| — | 0.11.0 | The docked reader — **shipped** | | A passage captured in the reader resolves back to its locus for page, video and web; no modal opens from the reader |
| — | 0.12.0 | The Brief — **parked** | | None; no rung waits on it |
| I. Every host | 0.13.0 | Every host is a first-class host — **in progress** on `feat/lighter-install`. **Checkpoint A** | #139, #24, #99, #79 (merges with it) | First run completes with no terminal on a Windows and a Linux machine that has never seen Luminary, and each is told the truth about its own accelerator |
| II. Stability | 0.14.0 | Gates you can believe | #50, #101, #88, #110 | `make ci` and `make smoke` both green, nothing quarantined to keep them so |
| | 0.15.0 | Stores that agree, output you can measure. **Checkpoint B** | #65, #63, #97, #100, #66 | A reprocess killed midway leaves no divergence between stores; every ingest path reports a measured fidelity number; no shipped default changes what a user receives without a number behind it |
| III. Reach | 0.16.0 | Capture, and device pairing | | Three source types round-trip from the browser to a readable document; an unpaired origin or a revoked device is refused |
| | 0.17.0 | The re-embed rail | | A full re-embed of a real library runs to completion, survives being killed, and resumes |
| | 0.18.0 | Your own server. **Checkpoint C** | | A container reachable beyond loopback refuses every request without a device token; a CPU-only server builds an enriched library with a key |
| IV. Other devices | 0.19.0 | Sync through storage the user controls | | Two machines that reviewed the same deck offline converge with every review from both kept; a snapshot copied mid-write is refused on open |
| | 0.20.0 | Mobile capture and review. **Checkpoint D** | | A phone reviews cards and takes notes with no connection, and both reach the library on reconnect with no review lost |
| V. Breadth | 0.21.0 | Anki import | | No imported card shows a grounding verdict it did not earn; its schedule comes from FSRS state, not copied SM-2 intervals |
| | 0.22.0 | Encoders and languages | | Non-English retrieval degradation measured on the current stack before any swap; a swap ships only through 0.17.0's rail |
| | 1.0.0-rc | The release candidate. **Checkpoint E** | | The checkpoint gate, green on the candidate build |
| | 1.0.0 | The public release | | Every rung's exit gate green together, on one build |

**1.0.0 itself carries no new features.** Work not on a rung above is 1.1, not 1.0. The open
issues not on a rung are 1.1 unless a rung pulls them in: PDF math as LaTeX (#137), figure-caption
quality (#124), nugget recall for answers (#121), Hub approximations (#103), parent-document
retrieval (#25), model-change configurability (#48), and a copy-link button for notes (#26, a
good first issue that can land at any time).

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

### 2. Every host is a first-class host — 0.13.0

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

**Still open after 0.13.1** (0.13.1 carried reader and keychain fixes only; 0.13.0 shipped with the
Linux T4 first run, `make ci`, `verify-dock` and `verify-citation` green; these were not run or not
fixed):

- A first run of the 0.13.0 installer on a real Windows machine, and `make smoke` there. CI installs
  it, ingests and searches (`desktop-installers.yml`); nothing has run the app past that.
- `make smoke` against the bundled macOS app, and the 0.13.0 DMG on a cleared data directory.
- Evals: `eval-ingest` reports a document this database lacks as "no chunks stored"
  (`evals/run_ingest_eval.py:115`); `eval-summary` replays stored summaries unless asked to refresh
  (`evals/run_summary_eval.py`, the `eval-summary` target); the flashcard judge's atomicity read
  1.0000 unverified, and a factuality outside its enum raises (`evals/lib/flashcard_metrics.py:189`).
- Flashcard factuality 0.78 and clarity 2.88, under their floors; predates 0.13.0, a product project.
- Ask answers a question whose premise the text does not hold with a bare "not found" (the Odyssey:
  "Mercury's plan" is Jove's), though the passage that corrects it was retrieved.
- Web articles keep Wikipedia's `[edit]` links in the chunk text.
- YouTube ingest unverified this release: YouTube refused the test machine as a bot, and the Linux
  box has no ffmpeg.
- `make measure-ttft` cannot run: `scripts/measure_ttft.py` was deleted in `97c3a78c` and the
  Makefile target still calls it.

**0.13.2: one-command installs on Windows and Linux** (on `feat/windows-linux-release`). The aim
for 1.0 is reach: any recent Windows or Linux machine either runs well or is told before the
download that it cannot, as an Intel Mac is today, and pointed at a cloud key or the hosted version.

| Item | Status |
|---|---|
| `get-luminary.sh` / `.ps1` install the latest release in one command | built, CI installs through them |
| SIGTERM drains the process tree on Linux and macOS; an AppImage without FUSE ends with its runtime | built |
| Off Apple Silicon the default text model is `qwen3.5:4b` whatever the host holds; other models are the user's pick in Settings | built |
| The one-command installers refuse before downloading where `host_support.local_inference_support` would, with its message, and offer to continue for reading, search and notes (`LUMINARY_INSTALL_ANYWAY=1` without asking); `test_get_luminary_script.py` fails if they disagree | built |
| A release job attaches the Windows setup, `.deb`, AppImage and their `.sha256` files; README carries the one-liners once a release does | open: a `publish` job for `desktop-installers.yml` is drafted, adding it needs the maintainer |
| One timing script over the installed app: book ingest (Think Python), Ask, flashcards, teach-back, on `qwen3.5:4b`; its baseline is the M3 Pro | open |
| Hard limits checked before any cloud run: installer size budget, path length, driver mode | open |

**Cloud runs: two boxes, same card, same model.** A Linux and a Windows `g4dn.xlarge` (T4), both on
`qwen3.5:4b`, so they differ by OS only. Each runs the one-command install, a first run with no
terminal, `make smoke` against the installed app, and the timing script. Windows needs AWS's gaming
driver, which runs the card in WDDM mode; if Ollama still reports no VRAM after ten minutes, the box
is terminated and the Windows GPU path goes to a volunteer. No CPU-only box is run: such a host is
refused, so timing it measures nothing. Parity is proposed as each timing within 1.5x of the M3 Pro.

**Not in 0.13.2.** Intel and AMD integrated graphics are refused as `no_accelerator`, though Ollama
serves them through Vulkan. That covers most current Windows laptops, and whether to admit them is
decided in 0.13.3 once one has been timed on `qwen3.5:4b`; AWS has no such machine. Code signing
(SmartScreen warns) is not in it either.

**Seams kept for the hosted version and mobile.** The host verdict has one owner,
`host_support.py`, served over HTTP, and the installers copy it under test. The default model lives
in `model_registry.py`. The engine is a setting (`llm_mode`) behind LiteLLM, and embedding,
retrieval and the learner record never move with it. Desktop-only code stays in `luminary-host` and
`src-tauri`, so the same backend can serve from a server.

**Exit gate.** First run completes with no terminal on a Windows and a Linux machine that has never
seen Luminary; each host's verdict names the accelerator it actually has, proven by a platform-pinned
test and a Windows CI job; a 16 GB host is not refused (#139); `make smoke` green on Windows. Then
Checkpoint A.

### 3. Gates you can believe — 0.14.0

`make ci` and `make smoke` green together with nothing quarantined to keep them so: 23 `pytest.mark.unstable`
markers across 14 files today (#50). Local green is necessary and not sufficient — GLiNER memory pressure
has produced GitHub-only failures no local run reproduces.

What the gate cannot pass without:

- **#50**: the quarantine itself, and 111 duplicated DB fixtures. Timing policies were tried on it and
  failed; the durable fix is per-site.
- **#101**: the entity-extraction test doubles take the wrong signature and always raise, so no
  ingestion test exercises extraction or its Kuzu writes. The three `integration_http` tests are
  skipped on GitHub, so upload-to-complete ingestion never runs where a release is gated.
- **#88**: the clustering holder was fixed in 0.11.0, but the reproduction that found it — smoke under
  60 concurrent `/qa` calls — has not been re-run. It closes on 0 lock errors under that load.
- **#110**: a route chunk can fail to load in the packaged app, cause unknown. The bundled backend
  logs no request status or latency, so the next occurrence cannot be diagnosed either; that logging
  is this rung's part.

This rung exists to shrink as the ladder runs. It grows only if a rung above it breaks the no-new-quarantine
rule, and that is the signal to move it back up.

### 4. Stores that agree, output you can measure — 0.15.0

A failed graph write is lost and SQLite and Kuzu diverge with nothing reconciling them (#65). Entity ingest
samples 2.4% of a long book and reindex disagrees with ingest (#63). The md/epub/docx/txt paths are
unmeasured, and audio ingested before 0.7.5 has no sections (#97); the parent-section duplication it
also named is fixed.

**What a user receives is measured before it is a default.** Two shipped behaviours change the answer
with no quality number behind them: the slow-host context budget halves the passages, and note
search's semantic arm is never scored on a query with no lexical overlap (#100). Suggested questions
are generated from section summaries rather than text, so they presuppose framings the document never
makes, and the ungrounded answer that follows renders like a grounded one (#66).

**Query-time graph expansion buys no retrieval quality.** `run_eval.py --ablation`, 2026-09-21, dev
library, GLiNER held resident and the arms confirmed to diverge before and after each dataset. On the
shipped funnel (rrf+rerank) HR@5 is identical with and without expansion on all five sets (book 40,
paper 40, legal/play/study 60 rows) and MRR moves by at most 0.003 in both directions, under one
question. Unreranked, no set moves by more than one question, in both directions. Measured: the
`_graph_expand` alias tokens on `/search`. Not measured: the chat `graph` node, which routes
relationship questions to Kuzu and not to `/search`.

**Expansion is also dormant in the shipped app.** `_graph_expand` skips when GLiNER is not loaded
(`retriever_strategies.py:370`), only startup warmup and ingestion load it, and the reaper releases it
after `NER_IDLE_RELEASE_SECONDS=180`. A user's search therefore expands only in the three minutes after
launch or an ingest. Given the ablation, the fix is to remove expansion from `/search`, not to keep
GLiNER resident for it.

**The store's fate is not settled by that number.** 28 modules read the graph store: the chat `graph`
node, graph flashcards, concepts, mastery, study paths and prerequisite extraction among them. Retiring
expansion removes one reader. Port-or-delete for the rest is decided here on what those features
deliver, alongside #65 (writes diverge from SQLite with nothing reconciling) and the Windows lock.
`RELATED_TO` is empty library-wide and 11.1% of co-occurrence edges pair an entity with itself.

**The last of the document-model work belongs here.** `form`, `domain` and `register` are written at ingest
by `_persist_classification` and `DocumentProfile` owns the policy, so what remains is retiring the legacy
`content_type` projection and `is_technical` now that 0.9.0 has shipped without them being the source of
truth. It is a migration, and migrations get more expensive with every user.

Then Checkpoint B: the app is stable enough that the next three rungs open it to the network.

### 5. Capture, and device pairing — 0.16.0

**A library stays empty when filling it means opening the app and finding the file.** The backend is
already HTTP on :7820, so an extension needs a POST rather than an architecture. One click for a page, a
PDF, a YouTube video or a selection with its source; a watch-folder for the desktop app; Markdown export
shaped for Obsidian and a Zotero read path.

**Pairing ships with it, not after it.** The backend is unauthenticated on localhost and CSRF is
deliberately open, so any page in any tab can already POST to :7820 — an extension turns a latent hole
into a documented invitation. The gate is that an unpaired origin is refused, proven by a test that
fails when pairing is removed.

**Pairing is the device authentication 0.18.0 and 0.20.0 reuse, so it is per device, not per origin.**
A one-time code shown by the desktop app is exchanged for a named, revocable token stored hashed. An
origin allowlist would serve the extension and nothing after it. The app's own origin stays tokenless on
loopback; any other origin needs a token. `TrustedHostMiddleware` in `main.py` pins loopback against DNS
rebinding, and that pin may only widen when authentication is on.

### 6. The re-embed rail — 0.17.0

**Build the migration, not the model swap.** Moving to a multilingual embedder regenerates every vector in
every library, and 0.x is the last point at which the compatibility promise is weak enough to absorb that —
but the argument is about the machinery, not about the model. A resumable, restartable re-embed path plus
the snapshot/restore format is the same work sync needs and the same work the OKF projection is (I-21).

Proven against the current 384-dim embedder, where a wrong answer costs nothing. The multilingual swap then
becomes 0.22.0's decision, backed by the measurement nobody has taken: how far the current stack actually
degrades on non-English text.

### 7. Your own server — 0.18.0

**Luminary on the user's own cloud.** The container is most of it already: `Dockerfile` plus
`LUMINARY_MODE=public` serves the SPA and the API on one port, and a compose volume holds the library.
**What is missing is authentication, and 0.16.0 builds it.** `docker-compose.yml` binds `127.0.0.1`
precisely because there is none, so until this rung ships, reaching the container from elsewhere is a
tunnel the user owns and the docs say so.

**A server with no GPU is an unsupported host.** `host_support.local_inference_support` answers
`container_without_accelerator` for a CPU-only container, so every local call is refused and
enrichment does not happen. This rung depends on 0.13.0's BYOK enrichment choice; without it a
reachable server serves an unenriched library.

### 8. Sync through storage the user controls — 0.19.0

iCloud Drive, OneDrive, Dropbox, Google Drive — storage the user already controls, so no account and no
server. **The live stores cannot be the thing that syncs**: SQLite with WAL, LanceDB and Kuzu are all
mid-write-sensitive, and a daemon copying a `-wal` or a Kuzu directory mid-write produces a corrupt library
on the other machine. What syncs is the snapshot format from 0.17.0, with the live stores rebuilt from it.
Conflict resolution is the reason this is a feature rather than a script: two machines that both studied
offline have divergent FSRS state, and last-writer-wins silently discards a review session.

### 9. Mobile capture and review — 0.20.0

Note taking and flashcard review — the two things done away from a desk. Reading and ingest stay on the
machine with the models. A phone that only works while the laptop is awake is not a client: against
0.18.0's server it works online, and offline it needs on-device storage plus 0.19.0's sync.
`surface-manifest.json` already declares each surface's mode, so a mobile build is a third mode rather
than a fork. It authenticates with 0.16.0's device tokens.

### 10. Anki import — 0.21.0

Export already ships — `export_service.py` writes a `.apkg` through genanki for a
collection's deck. There is no import path. The hard part is not the file format: a Luminary card carries
`source_chunk_ids` and a per-card grounding verdict (I-34, I-35), and an imported card has no passage in the
library to point at. Decide what grounding means for a card whose source is elsewhere — shown as ungrounded,
bindable to a document later, or held in a separate lane — before writing a parser, or the invariant quietly
stops meaning anything. FSRS state is the second question: an Anki deck carries SM-2 scheduling, and `fsrs`
v6 state is not the same shape, so importing intervals naively produces a schedule that looks continuous and
is not.

### 11. Encoders and languages — 0.22.0

**fp32 ONNX Runtime for the encoders moved to 0.13.0** (`lighter-install-plan.md`), as a size change
rather than a speed one: the same weights at fp32 measured cosine >= 0.99999982 against the shipped
embedder with identical top-10 retrieval, so it is not a re-embed. **A quantized ONNX encoder still is**,
and stays behind I-9 and 0.17.0's rail. Replacing only some of `optimum`, `sentence-transformers` and
`gliner` *increases* the bundle, since each declares torch unconditionally — which is why the plan
replaces all three. The encoders are not the latency bottleneck: a slow host's ~121s question is the
4B model at ~6 tok/s, served by Ollama. For an accelerated encoder, `onnxruntime-directml` is the broadest Windows execution provider
(NVIDIA, AMD, Intel Arc and Intel NPUs through one wheel) but publishes `win_amd64` only — Windows on
ARM is not covered by it, so a Snapdragon NPU needs a different provider, not the same binary.

**The multilingual embedder swap.** Embeddings are `BAAI/bge-small-en-v1.5`, 384-dim and English-only, and
every stored chunk, note, image and concept vector lives in that space. GLiNER is already multilingual
(`gliner_multi_pii-v1`), so entity extraction survives the move and retrieval does not. Interface localisation
is separate and seamed but unbuilt: every surface in `surface-manifest.json` carries `labels: {"en": ...}`.

## Deferred — decided, not scheduled

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
