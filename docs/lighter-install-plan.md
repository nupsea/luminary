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

- **scipy and scikit-learn are undeclared.** `clustering_service.py` (HDBSCAN) and
  `concept_nodes/build_hierarchy.py` (linkage) import them, but only sentence-transformers pulls them in.
  Both imports are lazy, so removing sentence-transformers passes boot and the import smoke test and
  fails at the first clustering run. Declare them directly before anything is removed, and add both to
  `REQUIRED` in `scripts/desktop/verify_imports.py`.
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
- **The artifact** is built in CI from the same checksummed Ollama archive `stage_ollama.sh` verifies,
  published as a Luminary release asset per OS, keyed to `OLLAMA_VERSION`. Its sha256 is compiled into
  the catalogue; the download resumes, is verified before extraction, and is extracted to a temporary
  directory then renamed into place. A pack for another Ollama version is never loaded, so an Ollama bump
  costs NVIDIA users a ~600 MB download — bump deliberately.
- **Offered when a driver is present:** `host_support` already reads `nvcuda.dll` on Windows and
  `/proc/driver/nvidia/version` on Linux. **The accelerator the app reports comes from Ollama's own
  discovery line after loading, never from the pack being present** (0.13.0 exit gate).
- **Open: whether Ollama loads runners from a second directory.** `supervisor.rs` passes one
  `OLLAMA_LIBRARY_PATH`. If Ollama searches only one tree, the engine's library directory has to live in
  `DATA_DIR` as a whole, copied there on first launch. Phase 0 decides this from `discover/runner.go` at
  v0.32.5 and a real load; the component design waits on it.
- **Open: redistribution terms.** The CUDA runtime libraries inside Ollama's archive are redistributable
  with an application; republishing them as a separate download is checked against NVIDIA's terms
  before the first asset is published.
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

| Phase | Work | Gate |
|---|---|---|
| 0. Measure | Windows stage breakdown from CI; ONNX speed on macOS arm64, Windows and Linux x86_64 with length-sorted batches and explicit thread counts; gliner's own ONNX fp32 against torch on the golden corpora; Ollama second-directory runner loading; CUDA redistribution terms; `evals/` independent of backend dependencies | every item answered with a recorded number or source line |
| 1. Hygiene | declare scipy and scikit-learn; the payload rules above; size and path budgets | `make ci`; Linux `.deb` and AppImage build and open in `desktop-installers.yml` |
| 2. Embedder and reranker on ORT | torch still installed | committed parity fixture (cosine >= 0.99999, identical top-10) in CI; `make eval` unchanged against a same-day baseline run twice; speed gate |
| 3. GLiNER on ORT | numpy processor and decoder | entity-agreement harness: identical (span, label) per chunk at 0.65 and 0.55, score diff < 1e-4 on the golden corpora, fired once against a deliberately broken port; resident memory measured |
| 4. Remove torch | dependencies, index, `lib.sh` branch, `verify_imports.py` | `make ci`; `verify-stage` on all three OSes; no `torch`, `transformers`, `sentence_transformers` or `gliner` import under `backend/app` |
| 5. CUDA component | pack build and publish, catalogue entry, shell discovery; installers drop `cuda_v13` | all three installers build, install and open; on a GPU host (AWS g4dn): fresh install reports Vulkan, after the pack Ollama's discovery reports CUDA, offline first run still works |
| 6. Windows decisions | signing, WebView2 mode, updater | each recorded here, then built |

**Speed gate.** The probe that measured parity also read ONNX slower: 16.42 s against 7.37 s for 460
embeddings, 18.89 s against 10.68 s for 600 rerank pairs, on Apple Silicon. That probe used unsorted
batches and default threads while sentence-transformers sorts by length, so the number is not yet a
finding. ORT must be no slower than torch on each OS for ingest embedding and reranking, or Phase 2 does
not ship.

## Risks

| Risk | Consequence if missed | Control |
|---|---|---|
| GLiNER port diverges | entities, graph edges and graph cards drift with no error; extraction is unmeasured today (`eval-coverage.md`) | agreement harness, fired on purpose; blocks Phase 4 |
| ORT slower on x86 | every ingest slower for every user | per-OS speed gate |
| A torch consumer hidden behind a lazy import | `ImportError` on one code path only, after release | import grep gate, `FORBIDDEN` list, scipy/scikit-learn declared first |
| Update re-downloads ~1.35 GB of encoder weights | first launch after update blocks on the embedder | stated in release notes; old weights removed only after the new ones load |
| Pack corrupt or tampered | engine fails to load, or runs foreign code | compiled-in sha256, verify before extract, atomic rename |
| Pack unreachable | NVIDIA host runs on Vulkan | degraded speed, never failure; reported as such |
| Stage creeps back toward 2 GB | installer stops building again | size budget in `verify_stage.sh` |
| An fp32 file silently swapped for a quantized one | vectors leave the space; I-9 | parity fixture pins the file's sha256 |

## Out of scope

Multilingual embedder (0.22.0), quantized encoders (0.17.0's rail), bundling model weights, Windows and
Linux arm64, `.msi`.
