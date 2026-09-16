---
description: Implementation plan for 0.13.0's installers - CUDA as an on-demand engine component, encoders on ONNX Runtime without torch, and the payload gates that keep every installer buildable. Deleted once it ships.
---

# Lighter install

Every installer builds with headroom, installs quickly, and carries nothing the app never runs. Two
structural changes do most of it, and both land inside 0.13.0 because each changes what an installed
copy looks like — changing that after users have installs is a migration per user:

1. **The engine installer ships CPU and Vulkan runners. CUDA 13 is a component fetched for a host with
   an NVIDIA driver.**
2. **The encoders run on ONNX Runtime, and torch, transformers, sentence-transformers and gliner leave
   the shipped dependency set.**

Status lives in `roadmap.md`; this file is the plan and is deleted when the work ships.

## Why

The Windows setup does not build. makensis fails with `Internal compiler error #12345: error mmapping
datablock` on a 2.28 GB stage (desktop-installers run 34961612107); NSIS cannot pack much past 2 GB.
Removing CUDA alone leaves ~350 MB of headroom that the next dependency bump spends. Removing torch
alone leaves the stage at ~1.8 GB, still one bump from the ceiling.

## Measured baseline

| Item | Size | Measured on |
|---|---|---|
| Windows stage | 2.28 GB: runtime 1.5 G, engine 751 M, payload 32 M | CI run 34961612107 |
| Windows engine | `cuda_v13` 629 M, `vulkan` 50 M, `ollama.exe` 35 M | same run |
| torch 2.10.0+cpu, win_amd64 | 404 MB unpacked, 11,721 files (wheel 113.7 MB) | wheel file listing |
| macOS stage `site-packages` | 1,346 MB, of which torch 340, transformers 111, networkx 9, torchgen 3, sentence_transformers 4, gliner 1 = 471 MB leave with torch | local `build/stage` |
| macOS stage | 37,681 files; longest path 199 chars (`litellm/proxy/.../guardrail_benchmarks/...`); 167 paths over 140 chars: litellm 93, transformers 39, torch 15 | local `build/stage` |
| DMG | 678 MB | v0.8.28 release artifact |

**Estimated** Windows stage after both changes: ~1.15 GB (runtime ~1.0 G assuming Windows transformers
matches macOS's 111 MB, engine ~120 M, payload 32 M). Re-measured in Phase 0 before any budget is set
from it.

## Encoders on ONNX Runtime

### Parity is measured, and it is why this is not a re-embed

Same model weights exported at fp32 produce the same vector space, so I-9 does not trigger. Measured
against the shipped sentence-transformers path on 400 dev-library chunks and 60 golden questions:

| Model | ONNX file | Result |
|---|---|---|
| `BAAI/bge-small-en-v1.5` | official `onnx/model.onnx`, 126.9 MB | cosine min 0.99999982, max abs diff 3.87e-07; top-10 retrieval identical for 60/60 queries |
| `cross-encoder/ms-marco-MiniLM-L-12-v2` | official `onnx/model.onnx`, 127.5 MB | score max abs diff 8.58e-06; top-5 order identical for 30/30 queries |

**Quantized variants are not covered by this.** The reranker repo's `qint8` files (32.7 MB) and
GLiNER's `int8` (332.9 MB) change outputs; an int8 embedder is a re-embed behind 0.17.0's rail. This
plan ships fp32 only.

The effective reranker is `settings.RERANK_MODEL` (MiniLM-L-12). `_RERANK_MODEL` (L-6) in
`retriever_strategies.py` is a fallback that never resolves while the setting has a default.

### Implementation facts

- Embedder: CLS pooling then L2 normalisation (`SentenceTransformer` modules are
  `Transformer, Pooling, Normalize`), `max_seq_length` 512, query prefix unchanged. Tokenised with
  `tokenizers`, which stays in the set because litellm requires it.
- Reranker: `max_length` 512, identity activation, pairs truncated `longest_first`.
- GLiNER is the hard part. gliner 0.2.25's ONNX path still imports torch — 21 modules do, including
  `onnx/model.py`, `data_processing/processor.py` and `decoding/decoder.py` — and the package declares
  torch unconditionally. The shipped model (`urchade/gliner_multi_pii-v1`) is a uni-encoder span model,
  `span_mode: markerV0`, `max_width` 12, `max_len` 384, whitespace word splitting, first-subtoken pooling.
  Going torch-free means porting `UniEncoderSpanProcessor` and `SpanDecoder` (greedy flat NER) to numpy
  against `onnx-community/gliner_multi_pii-v1`'s fp32 `onnx/model.onnx` (1,103.5 MB, the same download
  as today's 1,102.4 MB checkpoint). Keeping torch for GLiNER alone keeps the 404 MB and defeats the
  change, so it is not an option.
- `langchain_text_splitters` imports sentence-transformers inside `try/except ImportError`, so the
  chunkers keep working without it.
- `sympy` stays: onnxruntime requires it.

### Dependencies that move with it

- **scipy and scikit-learn were undeclared** until the Phase 1 change. `clustering_service.py`
  (HDBSCAN) and `concept_nodes/build_hierarchy.py` (linkage) import them, but only sentence-transformers
  pulled them in. Both imports are lazy, so removing sentence-transformers would pass `make ci` and fail
  at the first clustering run -- but not silently: both are already in `REQUIRED` in
  `scripts/desktop/verify_imports.py`, so a stage built without them fails stage-verify, before any
  installer is built. They are now direct dependencies in `backend/pyproject.toml`.
- torch, transformers, sentence_transformers and gliner move to `FORBIDDEN` in the same file.
- The torch pin, the `pytorch-cpu` index in `pyproject.toml` and the extra-index branch in
  `scripts/desktop/lib.sh` become dead code and go in the change that removes torch.
- `model_prefetch.specs()` fetches the ONNX file and tokenizer only; the `_OTHER_FRAMEWORKS` and
  `_DUPLICATE_TORCH_WEIGHTS` filters are rewritten for it.

### Cost to existing installs

An updated app downloads the ONNX files once: ~255 MB for embedder and reranker, 1.1 GB for GLiNER.
The embedder is a required startup phase (`startup_status`), so the first launch after the update
blocks on its ~127 MB. Old torch weights are deleted only after the ONNX model has loaded — never on
the assumption that the download succeeded.

## CUDA as an engine component

- **A GPU is used before the pack arrives.** Ollama v0.32.5 enables Vulkan by default
  (`envconfig.EnableVulkan(true)`), so an NVIDIA card runs through Vulkan on a fresh install, and CUDA is
  a speed upgrade rather than a precondition.
- **It rides the existing catalogue.** `components.py` and `/setup/components` already offer downloads
  with size and licence shown first; the pack is a new kind, `engine_runner`, installed under
  `DATA_DIR`, since the install directory is never written.
- **The artifact is Ollama's own release archive, not a Luminary one.** Ollama publishes no standalone
  CUDA asset, so there is nothing to mirror and no reason to republish; the whole archive is downloaded
  and one directory is kept out of it. `stage_ollama.sh` records the URL, the sha256 it already verified
  at stage time, and the member prefix in `ollama/engine-source.json`, and the catalogue reads that file
  rather than carrying a compiled-in constant. The download resumes, is verified before extraction, and
  is extracted to a temporary directory then renamed into place. The recorded version is the installed
  engine's, so an Ollama bump costs NVIDIA users the download again — bump deliberately. See "The CUDA
  runner is fetched from Ollama, not republished".
- **Offered when a driver is present:** `host_support` already reads `nvcuda.dll` on Windows and
  `/proc/driver/nvidia/version` on Linux. **The accelerator the app reports comes from Ollama's own
  discovery line after loading, never from the pack being present** (0.13.0 exit gate).
- **Answered: Ollama does not load runners from a second directory, and does not read
  `OLLAMA_LIBRARY_PATH` at all.** At v0.32.5 `ml.LibOllamaPath` is a package-level var computed once at
  init from `os.Executable()`, and `libOllamaPathCandidates` consults only the executable directory, the
  working directory and hardcoded relative paths — there is no environment branch in it.
  `OLLAMA_LIBRARY_PATH` appears only where the server exports it to the `llama-server` child, so the one
  `supervisor.rs` sets at spawn is inert; the current build works by accident of layout. A downloaded
  runner therefore cannot be pointed at, and the installed stage is read-only on Linux (`.deb` under
  `/usr`, AppImage entirely). **The engine tree is copied to `DATA_DIR` on first launch and spawned from
  there, and packs extract into it.** That is Phase 2, and the component design follows from it.
  Not yet verified by a real load from `DATA_DIR` — only from source.
- **Closed: there is no redistribution question left.** It existed only because the original design
  republished NVIDIA's libraries as a Luminary release asset. Fetching them from Ollama's own release
  removes the act that needed checking, so `cuda_eula.txt` never needed reading.
- macOS is unaffected (Metal).

## Payload rules that hold regardless

| Change | Reason | Guard |
|---|---|---|
| Prune `litellm/proxy/_experimental` (17 MB UI) and `guardrail_benchmarks` | the 199-char paths; nothing imports them. `litellm.proxy._types` stays (`desktop-bundle.md`) | import smoke test |
| Prune `libarrow_python_flight*` and `pyarrow/_flight*` with `libarrow_flight` | the leftover references the pruned library, which failed linuxdeploy on the AppImage | import smoke test, AppImage build |
| Size budget in `verify_stage.sh` | the 2 GB ceiling was found by three CI rounds; it must fail locally | fails above the per-OS budget |
| Path budget in `verify_stage.sh` | install prefix `C:\Users\<name>\AppData\Local\...` is ~60 chars against `MAX_PATH` 260 | fails on any stage path over 190 chars |
| Tracing packages out of the main set, if `telemetry.py` degrades without them | `PHOENIX_ENABLED` defaults to false, yet the OTLP gRPC exporter and instrumentation ship; `telemetry.py` imports `opentelemetry.trace` and `openinference.semconv` at module scope | `tests/test_telemetry.py`, measured size before and after |
| `LINUXDEPLOY_EXCLUDED_LIBRARIES` for `libcuda`, `libnvidia-*`, `libvulkan` | linuxdeploy resolves every ELF in the AppDir; driver libraries must come from the host | AppImage build, then launched by `verify_installed.sh` |
| `relink_bundled_libs()` records the directory an inherited RPATH already implied | RPATH is inherited by transitive loads, so auditwheel records `$ORIGIN/../<pkg>.libs` on the *extension* alone and Ollama records `$ORIGIN/lib/ollama` on the `ollama` executable alone. linuxdeploy inspects each ELF alone, so `pillow.libs/libfreetype` reads as missing `libpng16-*.so.16` and `lib/ollama/vulkan/libggml-vulkan.so` as missing `libggml-base.so.0` one directory above it -- the AppImage fails on a stage the `.deb` ships working. The search runs from the library's own directory up to the staged root and no wider, which is that same reach; a host-owned dependency is never found there | AppImage build; `patchelf` is required to stage on Linux |

linuxdeploy also rewrites rpaths of payload libraries. Whether that breaks the runtime is decided by
launching the AppImage, not by reasoning about it.

## Windows decisions this plan forces

| Decision | Current | Why it cannot wait |
|---|---|---|
| Code signing | unsigned; SmartScreen blocks with "Windows protected your PC" | reputation accrues per certificate, so the first public build should carry the one that stays |
| WebView2 install mode | `downloadBootstrapper`, needs network during install | Windows 11 ships WebView2; Windows 10 without it cannot install offline. `embedBootstrapper` is the alternative |
| Updater | none; every release is a full installer | tauri's updater replaces the installed tree; `DATA_DIR`, models and packs survive either way, so the layout above already allows it |
| Install time | unmeasured; 37,681 files, Defender scans each | torch alone is 11,721 files on Windows; measure the silent-install step before and after |
## Phases

Each phase ends on a gate that can come out red. A red Phase 0 answer re-opens this plan before code.

**Re-ordered 2026-09-16, after Phase 0.** The original order put the encoder port before the CUDA
component. Phase 0 measured the encoder port as the smaller and riskier lever of the two: ORT is
slower on the only OS measured, and removing torch frees ~441 MiB, not the 518 MiB projected, because
scipy and scikit-learn cannot leave with it. The CUDA runner is 629 MB of the 751 MB Windows engine
and moving it out drops the stage under the NSIS ceiling on its own. So the packaging lever ships
first and the encoder port becomes optional headroom, gated on x86 numbers that do not exist yet.

**Every phase ends with all three installers building, installing and opening.** No phase leaves
Windows broken until the next one lands; a red gate is reverted or descoped, never patched around.

| Phase | Work | Gate |
|---|---|---|
| 0. Measure | Windows stage breakdown from CI; ONNX speed on macOS arm64, Windows and Linux x86_64 with length-sorted batches and explicit thread counts; gliner's own ONNX fp32 against torch on the golden corpora; Ollama second-directory runner loading; CUDA redistribution terms; `evals/` independent of backend dependencies | every item answered with a recorded number or source line |
| 1. Hygiene | declare scipy and scikit-learn; the payload rules above; size and path budgets; installer size reported in CI | `make ci`; Linux `.deb` and AppImage build and open in `desktop-installers.yml`; both budgets fired on purpose once |
| 2. Engine to `DATA_DIR`, and one downloader | copy the engine tree to `DATA_DIR` on first launch and spawn from there; a resumable, sha256-verified, extract-to-temp-then-rename downloader behind `/setup/components`; `engine_runner` kind; installers drop `cuda_v13` | Windows NSIS builds, installs silently and opens; stage within the Phase 1 budget; engine runs from `DATA_DIR` on Windows and Linux, and from the bundle on macOS, which has no runner to fetch; the verifier fired once against a corrupted artifact |
| 3. CUDA component | keep the offer to machines with an NVIDIA driver | on a GPU host (AWS g4dn): fresh install reports Vulkan, after the runner Ollama's discovery reports CUDA, offline first run still works |
| 4. First run | GLiNER becomes an explicit opt-in component; resumable progress for the remaining weights; WebView2 install mode; `MIN_FREE_BYTES` and the model-size wording corrected; Windows install time measured | first run completes with no terminal on a Windows and a Linux machine that has never seen Luminary, and each is told the truth about its own accelerator |
| 5. Encoders on ORT, conditional | x86_64 speed measured in CI **before** any port; then embedder and reranker behind the existing seams; torch removed; GLiNER last | committed parity fixture (cosine >= 0.99999, identical top-10) in CI; `make eval` unchanged against a same-day baseline run twice; speed gate. A red x86 gate ends this phase and is recorded as the answer |
| 6. Windows decisions | signing, updater | each recorded here, then built |

### The CUDA runner is fetched from Ollama, not republished

Ollama publishes no standalone CUDA asset. The v0.32.5 release carries seventeen files, and the
runner exists only inside the two base archives -- `ollama-windows-amd64.zip` (1,457,824,795 bytes)
and `ollama-linux-amd64.tar.zst` (1,422,353,729). ROCm and MLX ship separately; CUDA does not.

So the download is the whole archive and only `lib/ollama/cuda_v13/` is kept out of it: 628.8 MB
across 13 files on Windows, read from the zip's central directory. That costs the user about
760 MB more than a purpose-built pack would, and in exchange there is no release asset to publish,
no checksum to keep in step with each Ollama bump, and no NVIDIA redistribution question -- the
user fetches NVIDIA's libraries from Ollama's own release, which is what Phase 3's blocking legal
check existed to avoid. Revisit only if the download size proves painful in practice.

Two details that decide whether the extraction works, both read from the real archives rather than
assumed. Members are named `lib/ollama/cuda_v13/...` with no `./` prefix, in both. And the CUDA
directory is mostly **symlinks** -- `libcublas.so.12 -> libcublas.so.12.8.5.5` -- stored *before*
the file they point at. An extractor that keeps only regular files writes every real library and
none of the sonames the loader resolves, which looks exactly like a successful install.

### What Phases 1 and 2 put in the tree

The pieces a later phase builds on, so that nothing here has to be re-derived from the diff. Status
of each phase is in `roadmap.md`; this is the inventory.

| Piece | Where | What it is |
|---|---|---|
| `engine_dir()` / `relocate_engine()` | `src-tauri/src/stage.rs` | copies the engine to `DATA_DIR/engine` and spawns from there, keyed on the `ollama/ENGINE_VERSION` stamp. Copies aside and renames, so an interrupted copy cannot replace a working engine. `RELOCATE_ENGINE` is the one platform-dependent line; the mechanism compiles and is tested everywhere |
| `ENGINE_VERSION`, `engine-source.json` | written by `scripts/desktop/stage_ollama.sh` | the stamp the shell compares against, and the archive record the catalogue reads. The JSON is validated as JSON at stage time; its absence means "nothing to offer here", never an error |
| `download_verified()` | `backend/app/services/component_download.py` | resumable (`Range`, with 200/206/416 all handled), sha256 checked before the file is published, and the partial deleted on mismatch |
| `extract_prefix()` | same file | zip and `.tar.zst`, one member prefix only, every path contained, symlinks deferred to a second pass |
| `install_archive_subset()` | same file | the two composed, emitting the streaming progress events `/setup/components` already carries |
| `engine_runner` kind | `backend/app/services/components.py` | `engine_source()`, `engine_lib_dir()`, the catalogue entry, install and removal. Offered only where `engine-source.json` exists, which is Windows and Linux |
| shipped-library resolution check | `scripts/desktop/verify_ollama.sh` | every `NEEDED` that the engine tree itself ships must resolve from inside that tree; one the host owns is skipped, because a CI runner has no Vulkan loader. This is the only gate that covers `vulkan/libggml-vulkan.so`, which no CPU-only runner ever loads. It reports the edge count, so a version that stops depending on anything fails as a dead check rather than passing |
| size and path budgets | `scripts/desktop/lib.sh`, `verify_stage.sh` | fail the build above the per-OS byte budget or on any stage path over 190 chars. `scripts/macos/verify_stage.sh` reports size and is deliberately not gated — a DMG has neither ceiling |
| `zstandard`, `scipy`, `scikit-learn` | `backend/pyproject.toml` | were transitive by accident; the Linux runner is a `.tar.zst` and clustering needs the other two |

**What Phase 3 still needs.** `host_support._has_accelerator()` answers "any accelerator" and
conflates NVIDIA with AMD (`_WINDOWS_DRIVER_DLLS` holds both; `/dev/kfd` is AMD's). The CUDA runner
must be offered only where an NVIDIA driver is present, so a vendor-aware probe is needed — and that
function carries an explicit warning against a second copy of the policy, so `_has_accelerator()` has
to be refactored to read from the new one, never duplicated beside it.

### Decisions taken, and what each one cost

| Decision | Instead of | What it bought, and what it cost |
|---|---|---|
| Ship the packaging lever first, hold the encoder port | porting encoders to ORT first | the CUDA runner is 629 MB of the 751 MB Windows engine and carries no numerical risk; the port frees ~441 MiB and is red on the only OS measured |
| Fetch the runner from Ollama's release | publishing a Luminary CUDA asset | no release asset, no per-bump checksum, and no NVIDIA redistribution check — which was Phase 3's blocker. Costs the user ~760 MB of download they discard |
| Copy the engine to `DATA_DIR` | pointing Ollama at a second runner directory | Ollama v0.32.5 has no environment branch in runner discovery, so there was no second option. Costs ~122 MB of disk, once |
| macOS keeps running from the bundle | relocating on all three, as the phase gate said | its archive carries Metal and there is no runner to fetch, so a copy would spend disk for nothing. The gate wording was amended rather than quietly missed |
| Read `engine-source.json` at runtime | a compiled-in URL and checksum | the installed engine and the archive it came from can never disagree, because the stage writes both |
| Small installer, fetch on first run | bundling weights | already the status quo; the first-run download is what Phase 4 attacks |
| One encoder stack on every OS, if the port happens | ORT on Windows/Linux, torch on the dev Mac | the dev machine runs what users run |
| No CI cache for `build/pythons` | caching the standalone interpreter between runs | `uv python install` fetches it in under two seconds and restoring the cache took longer than that, while the directory holds uv's minor-version link -- a reparse point on Windows that `actions/cache` restores as something uv cannot remove (`failed to remove directory cpython-3.13-windows-x86_64-none: The directory name is invalid. (os error 267)`). The cache paid nothing and cost a red Windows build. `release-macos-app.yml` still caches it, where POSIX symlinks survive the round trip |

### Cleanup once this ships

To be done when the phases are green, not before — each item is live code until then.

- Delete this file. It is a plan, and `docs/` carries only what exists.
- Fold what outlives it into the permanent docs: the runner-discovery finding, the symlink trap and
  the auditwheel-versus-linuxdeploy rpath finding into `docs/desktop-bundle.md`, and anything that
  became a rule into `docs/invariants.md` via the `invariant-capture` skill.
- Reconcile `CHANGELOG.md` and `docs/roadmap.md` against what CI actually proved, not against what
  was intended.
- If Phase 5 ends red, the torch pin, the `pytorch-cpu` index and the extra-index branch in
  `scripts/desktop/lib.sh` stay; if it ends green they go in the same change that removes torch.
- Retire whichever of the Phase 0 probe scripts and measurement arms no longer have a question.

**Speed gate.** ORT must be no slower than torch on each OS for ingest embedding and reranking, or
Phase 5 does not ship.

macOS arm64, embedder only, 460 chunks, batch 128, `max_len` 512, 12 intra-op threads, median of
four repeats, each pipeline timed end to end in one region:

| pipeline | median | emb/s |
|---|---|---|
| shipped sentence-transformers | 6.68 s | 68.8 |
| ORT fp32, BERT-fused graph, token-length-sorted batches | 6.86 s | 67.1 |
| torch, same token-length-sorted batches | 3.95 s | 116.4 |

**Against the shipped path ORT is 2.6% slower; against torch in the same pipeline it is 1.73x
slower. The gate as written compares against torch, so macOS is red.** The two readings differ
because sentence-transformers sorts by character length, not token length: its four batches pad to
widths 308/298/258/134, or 120,776 padded tokens, where token-sorted batches pad to 95/126/191/308,
or 76,144. Fixing that sort is a 1.69x win on the torch path we ship today and owes nothing to this
plan.

Forward pass alone, both engines handed identical pre-tokenised batches, so neither tokenisation
(17 ms) nor padding (4 ms) is inside the number: torch 3.94 s, ORT unfused 8.41 s, ORT fused 7.05 s.
`ORT_ENABLE_ALL` does not fuse attention on its own -- the optimised graph holds 0 `Attention`, 60
`Transpose` and 180 `MatMul` nodes. The offline pass (`onnxruntime.transformers.optimizer
--model_type bert --num_heads 12 --hidden_size 384`, a build-time step needing `onnx` and `sympy`,
133 MB output) fuses 12 `Attention`, 24 `SkipLayerNormalization` and 1 `EmbedLayerNormalization`
and is worth 1.19x. **The graph shipped must be the fused one; the stock HF export leaves 19% on
the floor.** The residual 1.79x is kernels: torch is built `BLAS_INFO=accelerate` and reaches AMX,
ORT's MLAS uses NEON. Threads and the CPU arena are exhausted as levers -- 6 threads 8.64 s against
12 threads 8.41 s, arena disabled 8.42 s.

Parity held on every arm, minimum cosine 0.9999998. No chunk in this corpus
reaches `max_len` (tokens median 120, p90 224, max 308), so long sequences are unexercised. Windows
and Linux x86_64 are not measured and do not follow from this number: on x86 torch has no Accelerate
equivalent, so the gap there is a separate question.

**Rerank gate, macOS arm64.** Shaped like the shipped call: L-12 cross-encoder, 10 golden questions
x `RERANK_DEPTH` 50 candidates, `batch_size` 32, 12 intra-op threads, median of three repeats.

| pipeline | 500 pairs | per query |
|---|---|---|
| shipped `CrossEncoder.predict` | 8.76 s | 906 ms |
| torch, token-length-sorted batches | 6.19 s | 601 ms |
| ORT fp32 fused, token-length-sorted | 12.39 s | 1213 ms |

**ORT is 1.41x slower than the shipped path and 2.00x slower than torch in the same pipeline, so
rerank is red on macOS under either reading of the gate.** The embedder's escape route does not exist
here: the shipped path pads 144,792 tokens against 107,812 token-sorted, a 1.34x waste worth 1.42x,
and ORT hands all of it back and more. Rerank runs on the chat path, so the cost is +307 ms per query
as the user feels it.

Parity: maximum absolute logit delta against the shipped path 5.7e-6 for ORT and 3.8e-6 for
token-sorted torch; top-5 order identical 10/10 for both. The candidates were sampled at random
rather than retrieved, so every logit sits near -11.2 inside a 0.25 spread and adjacent gaps are
about 5e-3 -- three orders above the disagreement, so the ordering result stands, but this is not a
parity test on realistic candidate sets.

The reranker has no ONNX export on the hub; it was exported here with `torch.onnx.export` (opset 17,
dynamic batch and sequence axes) and then fused by the same BERT pass, which is a second build-time
step needing torch, `onnx` and `sympy`.

**CoreML is not an option for this graph.** `CoreMLExecutionProvider` splits the 623-node bge-small
graph into 97 partitions and compiles each partition per distinct input shape. Dynamic batch widths make
every batch a new shape, so compiled models accumulate with nothing freeing them: on 2026-09-16 the arm
reached about 50 GB resident and was killed before it printed a single number. A fixed input width would
be the only way to probe it, and it would change what is being measured. Any execution-provider probe
runs under `scripts/capped_run.sh`, which kills the process tree past `MEM_CAP_GB` (default 12).

## Risks

| Risk | Consequence if missed | Control |
|---|---|---|
| GLiNER port diverges | entities, graph edges and graph cards drift with no error; extraction is unmeasured today (`eval-coverage.md`) | agreement harness, fired on purpose; blocks Phase 4 |
| ORT slower on x86 | every ingest slower for every user | per-OS speed gate |
| A torch consumer hidden behind a lazy import | `ImportError` on one code path only, after release | import grep gate, `FORBIDDEN` list, scipy/scikit-learn declared first |
| Update re-downloads ~1.35 GB of encoder weights | first launch after update blocks on the embedder | stated in release notes; old weights removed only after the new ones load |
| Archive corrupt or tampered | engine fails to load, or runs foreign code | the sha256 `stage_ollama.sh` verified, carried in `engine-source.json`; checked before extraction, atomic rename, and the partial file deleted on mismatch so a retry never resumes onto bad bytes |
| Archive unreachable | NVIDIA host runs on Vulkan | degraded speed, never failure; reported as such |
| The runner's symlinks dropped on extraction | every real library present and none of the sonames the loader resolves — an install that reports success and cannot start | `extract_prefix` defers links to a second pass; `test_engine_runner_download.py` fails if a versioned soname arrives as anything but a link |
| Stage creeps back toward 2 GB | installer stops building again | size budget in `verify_stage.sh` |
| An fp32 file silently swapped for a quantized one | vectors leave the space; I-9 | parity fixture pins the file's sha256 |

## Out of scope

Multilingual embedder (0.22.0), quantized encoders (0.17.0's rail), bundling model weights, Windows and
Linux arm64, `.msi`.
