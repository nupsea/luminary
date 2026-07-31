# macOS desktop bundle

How Luminary is packaged as a signed `.app` a user drags to Applications and
opens — no terminal, no Homebrew, no separate Ollama install, no `.env`.

Read this before changing `scripts/macos/`.

## Layout

`build/stage` is assembled to become `Contents/Resources` verbatim:

```
stage/                        <- Contents/Resources
├── surface-manifest.json     boot-fatal if missing
├── frontend/dist/            public-mode SPA
├── backend/{app,alembic,alembic.ini,pyproject.toml}
├── python/                   relocatable CPython + all dependencies
├── ollama/{ollama,llama-server}
└── licenses/
```

The tree mirrors the repo because `backend/app` resolves `surface-manifest.json`,
`frontend/dist`, `alembic.ini` and `pyproject.toml` through
`Path(__file__).resolve().parents[2]` — which, from `stage/backend/app/config.py`,
is `stage`. Same contract the release tarball already relies on
(`.github/workflows/release.yml`).

Everything writable lives in `~/Library/Application Support/sh.luminary.app/`:
`luminary.db`, `vectors/`, `graph.kuzu`, `models/`, `ollama/models/`, `.env`.
Nothing is ever written inside the bundle — it is read-only and code-signed, and
a write would break the signature.

## Shell

`src-tauri/` is a Tauri v2 crate. It opens a window on a bundled boot page,
starts both children, waits for the backend to accept connections, then
navigates the window to the backend's own origin.

Serving the SPA from the backend keeps it same-origin with the API, so neither
CORS nor `TrustedHostMiddleware` needs relaxing — a webview on
`tauri://localhost` calling `127.0.0.1` would be blocked by both.

- **Ports are allocated at launch** (`bind` to `:0`, read, release). Fixed ports
  collide with a user's own Ollama on 11434 or an older Luminary on 7820.
- **Both children start from `env_clear()`**, so a user's `DYLD_*`, `PYTHON*` or
  `VIRTUAL_ENV` cannot reach them. `PATH` is rebuilt to include
  `<stage>/python/bin`, which is where `yt-dlp` lives.
- **Both pipes are drained.** An undrained pipe fills its 64KB buffer and blocks
  the child on its next write; uvicorn logs to stderr, so piping stderr without
  a reader wedges the backend seconds into startup.
- **The backend's working directory is `DATA_DIR`**, which turns the
  CWD-relative `.env` lookup into a user-editable file in a findable place.
- **Single instance is enforced** by `tauri-plugin-single-instance`. Kuzu takes
  an exclusive file lock, so a second instance cannot open the library at all.
- **Children are killed on exit** for the same reason: a survivor holds that
  lock against the next launch.

The staged payload is found via `LUMINARY_STAGE`, then `resource_dir()`, then
`build/stage`, so the shell is runnable before there is anything to sign.

`make desktop-dev` runs it against `build/stage`; `make desktop-app` produces an
unsigned `Luminary.app`. Signing and notarization are not wired up yet.

The app icon in `src-tauri/icons/` is a placeholder generated from the web
logo and needs replacing with real artwork before release.

The SPA is served from `http://127.0.0.1:<port>`, which Tauri treats as a
remote URL, so `window.__TAURI__` is **not** injected into it. Only the boot
page can use IPC. Any desktop-only affordance in the SPA — revealing the
library in Finder, for instance — needs a capability granting IPC to that
origin first.

## Scripts

| Script | Does |
|---|---|
| `stage_payload.sh` | Backend source, SPA, manifest, license notices. Strips `code_executor`. |
| `stage_python.sh` | Relocatable interpreter + every dependency. |
| `stage_ollama.sh` | Bundled inference server, thinned to arm64. |
| `verify_stage.sh` | Relocatability + import + real boot of the staged backend. |
| `verify_ollama.sh` | Structure + a real pull and generation. |

`make stage` runs all three staging steps; `make verify-stage` runs both verifiers.

## Python runtime

Dependencies are installed into a `python-build-standalone` distribution's own
`site-packages`, not a venv. A venv records an absolute `home =` in
`pyvenv.cfg`, and `uv venv --relocatable` only rewrites console-script shebangs.
CPython derives `sys.prefix` by walking up from the resolved executable to the
`lib/python3.13/os.py` landmark, and the PBS binary links
`@executable_path/../lib/libpython3.13.dylib`, so a directory copy relocates
with no absolute paths.

Constraints that fall out of that, each enforced in `stage_python.sh`:

- PBS ships an `EXTERNALLY-MANAGED` marker; `uv pip sync` refuses to install
  until it is removed.
- The backend reaches `sys.path` through the relative `.pth` line
  `../../../../backend`. The app launches with `python -I`, which drops
  `PYTHONPATH` and `PYTHONHOME` so a user's own Python cannot leak in — leaving
  the `.pth` as the only route.
- Byte-compiled with `--invalidation-mode unchecked-hash`. `ditto`, DMG creation
  and notarization rewrite mtimes, which would invalidate timestamp-based `.pyc`
  and send a read-only bundle trying to rewrite them.
- uv's hardlinks back into `~/.cache/uv` are broken after install. Otherwise
  `codesign --force` mutates the shared cache inode instead of the bundle's copy.
- Console-script shebangs are rewritten to the sh/Python trampoline below, since
  uv writes them pointing at the build machine's interpreter. They cannot just be
  deleted — `youtube_downloader.py` spawns `yt-dlp` off `PATH`, so the sidecar's
  `PATH` must include `<Resources>/python/bin`.

  ```sh
  #!/bin/sh
  ''''exec "$(dirname "$0")/python3.13" "$0" "$@" # '''
  ```

- `_sysconfigdata__*.py` records the build machine's path and is rewritten to a
  synthetic prefix.

### Prunes that look safe and are not

Prunes are guarded by the import smoke test, not by reasoning:

- **`litellm/proxy`** (27 MB). `litellm_core_utils.litellm_logging` imports
  `integrations.gcs_bucket` at module scope, which imports `litellm.proxy._types`
  — plain `import litellm` needs it.
- **`libarrow_substrait`** (and `_dataset`, `_acero`). `pyarrow/lib.*.so` links
  all three directly; removing substrait breaks `import pyarrow` and cascades
  into `lancedb`, `sentence_transformers` and `gliner`. Only `libarrow_flight`
  is unreferenced.
- **`pip`** is kept deliberately — post-install components need it.

### `LC_ID_DYLIB` is not a dependency

`otool -L` lists a library's own install name first, and that name records where
it was built: PBS's prefix for `libpython3.13.dylib`, a `/Users/runner/...` tree
for `pymupdf/_extra.so`, `/opt/homebrew/opt/libomp` for torch's `libomp.dylib`.
Consumers resolve through `@rpath`, so those are identity, not linkage. A check
for external linkage must exclude the install name (`otool -D`) or it reports
three false positives. Excluded, the stage has zero external linkage.

## Ollama

Ollama is bundled rather than raw `llama-server`, so the LiteLLM `ollama/`
provider, model registry, pull progress, `keep_alive` and vision handling work
unchanged. It runs on a private port with its own `OLLAMA_MODELS`, leaving a
user's existing Ollama.app untouched and off 11434.

Source is the official `ollama-darwin.tgz`. A Homebrew tree cannot be bundled —
it symlinks `mlx_metal_v3/libmlxc.dylib` into `/opt/homebrew`.

Staging drops 404 MB to 43 MB (`ollama` + `llama-server`):

| Removed | Size | Reason |
|---|---|---|
| 22 `libggml*`/`libllama*`/`libmtmd*` dylibs | 32 MB | x86_64-only, the Intel runner's. `llama-server` is arm64 and statically embeds ggml and Metal. |
| `mlx_metal_v3/`, `mlx_metal_v4/` | 323 MB | MLX serves MLX-format models only; GGUF runs through `llama-server`. **The shipped model set is GGUF-only as a result** — adding an MLX model means restoring these. |
| Intel slice of `ollama` | 37 MB | Universal binary, thinned to arm64. |

The archive is flat: `ollama`, `llama-server` and the runner libs sit side by
side, so `OLLAMA_LIBRARY_PATH` points at that directory. The `lib/ollama/`
nesting is Homebrew-specific.

Model pulls use `POST /api/pull` over HTTP, so nothing needs an `ollama` binary
on `PATH` — which is what makes provisioning work from a GUI-launched process.

## Post-install components

Optional pieces are installed after the app, from the catalogue in
`app/services/components.py`, via `GET|POST|DELETE /setup/components`. That
catalogue is the single source of truth for model names.

Two things must stay out of the installer:

| Component | Kind | Why not bundled | Installs to |
|---|---|---|---|
| `transcription` (faster-whisper) | `python_extra` | Pulls PyAV, whose wheels bundle `libx264`/`libx265` (GPL-2.0-or-later). `libavcodec`/`libavformat`/`libavfilter`/`libavdevice` hard-link them via `@loader_path`, so they cannot be stripped from the wheel. | `DATA_DIR/extras` |
| `ffmpeg` | `tool` | Static builds carrying x264/x265 are GPL. | `DATA_DIR/bin` |

Luminary is Apache-2.0, so GPL code must not travel inside a distributed
installer. `faster-whisper` therefore sits in its own `media` dependency group,
which the bundle does not install; `AudioTranscriber.__init__` raises through
`require_extra(..., group="media")` until the component is present.

`licence` is a field on every catalogue entry and is shown before a download
starts. `test_setup_and_paths.py` asserts that copyleft entries are marked as
not distributed, and that `faster-whisper` stays out of `full`.

**Resolution.** `resolve_tool()` searches `DATA_DIR/bin` before `PATH`;
`activate_extras()` adds `DATA_DIR/extras` to `sys.path` during startup, before
anything imports from it. A GUI-launched process gets a minimal environment and
cannot rely on a user's shell.

**What the UI may offer.** `GET /setup/capabilities` reports what this install
can actually ingest, so the frontend does not encode which component enables
which feature — video needs both a transcriber and ffmpeg, and a YouTube URL
needs yt-dlp on top of those. `UploadDialog` hides the Web URL tab, the
audio/video content types and the media file extensions accordingly. Two mode
axes apply: `surface-manifest.json` decides what is built, capabilities decide
what is offered at runtime.

**Installation.** `python_extra` components use the bundled `pip` with
`--target`, never the bundle's own `site-packages` — that tree is read-only and
code-signed. This is why `pip` is not pruned from the staged runtime. There is
no automatic uninstall for them: `pip --target` cannot remove, and deleting the
extras directory would take unrelated components with it.

## Constraints

- **Apple Silicon, macOS 14+.** `lancedb` publishes no macOS x86_64 wheel and
  `onnxruntime` cp313 ships only `macosx_14_0_arm64`.
- **Model weights are not bundled.** ~3.5 GB of encoder and LLM weights are
  fetched on first run behind a progress UI.
- **`torch` ships in v1.** `optimum`, `sentence-transformers` and `gliner` each
  declare `torch` unconditionally, so moving the encoders to ONNX via `optimum`
  *increases* size. Dropping torch means replacing all three, and yields nothing
  until GLiNER is the last one done. Tracked separately, eval-gated.
