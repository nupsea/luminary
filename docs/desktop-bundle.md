# macOS desktop bundle

How Luminary is packaged as a signed, double-clickable `.app`, and the measured
facts that shape it. Read this before touching `scripts/macos/`.

The goal is a `Luminary.dmg` a non-technical user can drag to Applications and
open — no terminal, no Homebrew, no separate Ollama install, no `.env`.

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

## Scripts

| Script | Does |
|---|---|
| `stage_payload.sh` | Backend source, SPA, manifest, license notices. Strips `code_executor`. |
| `stage_python.sh` | Relocatable interpreter + every dependency. |
| `stage_ollama.sh` | Bundled inference server, thinned to arm64. |
| `verify_stage.sh` | Relocatability + import + real boot of the staged backend. |
| `verify_ollama.sh` | Structure + a real pull and generation. |

`make stage` runs all three staging steps; `make verify-stage` runs both verifiers.

## Measured facts

These were established empirically during the M0 spike. Several contradict the
obvious assumption, so they are recorded rather than re-derived.

### Python runtime: a distribution, not a venv

We install dependencies directly into a `python-build-standalone` distribution's
own `site-packages`. **Not** a venv: a venv always writes an absolute
`home = ...` into `pyvenv.cfg`, and `uv venv --relocatable` only rewrites
console-script shebangs, not that. CPython derives `sys.prefix` by walking up
from the resolved executable to the `lib/python3.13/os.py` landmark, and the PBS
binary links `@executable_path/../lib/libpython3.13.dylib`, so a plain directory
copy relocates with zero absolute paths.

- **PBS ships an `EXTERNALLY-MANAGED` marker** and `uv pip sync` refuses to
  install without it removed. We delete it from the staged copy: this is a
  private runtime we own and ship, so the marker does not apply.
- **The backend reaches `sys.path` via a relative `.pth`.** We launch with
  `python -I`, which drops `PYTHONPATH` (and `PYTHONHOME`, and user site — the
  point is that a user's own Python cannot leak in). `site.addpackage` joins each
  `.pth` line against the site directory, so the relative line
  `../../../../backend` resolves to the stage root and travels with the bundle.
- **Byte-compiled with `--invalidation-mode unchecked-hash`.** `ditto`, DMG
  creation and notarization all rewrite mtimes, which would invalidate every
  timestamp-based `.pyc` and send a read-only bundle trying to rewrite them.
- **Hardlinks back into the uv cache must be broken.** uv installs by hardlinking
  from `~/.cache/uv`; if those survive, a later `codesign --force` would mutate
  the shared cache inode instead of our copy.
- **Console scripts need a relocatable shebang.** uv writes `bin/*` entry points
  with an absolute shebang pointing at the build machine's interpreter. They
  cannot simply be deleted: `youtube_downloader.py` resolves `yt-dlp` through
  `PATH` and spawns it as a subprocess. We rewrite the shebang as the standard
  sh/Python polyglot trampoline, so `sh` execs the bundled interpreter by
  relative path while Python still parses the line as a string literal:

  ```sh
  #!/bin/sh
  ''''exec' "$(dirname "$0")/python3.13" "$0" "$@" #'''
  ```

  The sidecar's `PATH` must therefore include `<Resources>/python/bin`.

- **`_sysconfigdata__*.py` leaks the build machine's path** and is sanitized to a
  synthetic prefix. Nothing in a shipped bundle compiles extensions, so those
  config vars are inert, but the recorded path both leaks a local layout and
  points somewhere that does not exist on a user's Mac.

### `LC_ID_DYLIB` is not a dependency

`otool -L` lists a library's own install name first, and that name routinely
records where it was *built*: PBS's prefix for `libpython3.13.dylib`, a
`/Users/runner/...` tree for `pymupdf/_extra.so`, `/opt/homebrew/opt/libomp` for
torch's `libomp.dylib`. That is identity, not linkage — every consumer here
resolves through `@rpath`. Any check for "links outside the bundle" must exclude
the install name (`otool -D`) or it produces three guaranteed false positives.
Once excluded, the stage has **zero** external linkage.

### Prunes that look safe and are not

Every prune is guarded by the import smoke test rather than reasoned about,
because two obvious-looking ones turned out to be load-bearing:

- **`litellm/proxy`** (27 MB). `litellm_core_utils.litellm_logging` imports
  `integrations.gcs_bucket` at module scope, which imports
  `litellm.proxy._types` — so plain `import litellm` needs it.
- **`libarrow_substrait`** (and `_dataset`, `_acero`). `pyarrow/lib.*.so` links
  all three directly, so removing substrait breaks `import pyarrow` outright and
  cascades into `lancedb`, `sentence_transformers` and `gliner`. Only
  `libarrow_flight` is genuinely unreferenced.

### Ollama: 404 MB of tarball, 43 MB of it useful

We bundle Ollama rather than raw `llama-server` so the backend's LiteLLM
`ollama/` provider, model registry, pull-with-progress, `keep_alive` and vision
handling keep working unchanged. We run our own instance on a private port with
its own `OLLAMA_MODELS`, so a user's existing Ollama.app is never touched and
there is no contention on 11434.

- **Use the official `ollama-darwin.tgz`.** A Homebrew tree cannot be bundled: it
  contains a `mlx_metal_v3/libmlxc.dylib` symlink into `/opt/homebrew` that would
  dangle on every user's machine.
- **The official tarball is flat.** `ollama`, `llama-server` and the runner libs
  all sit side by side; there is no `lib/ollama/` subdirectory. That nesting is
  Homebrew-specific. `OLLAMA_LIBRARY_PATH` therefore points at the directory
  itself.
- **Every `libggml*` / `libllama*` / `libmtmd*` dylib in the tarball is
  x86_64-only** — the Intel runner's. `llama-server` is arm64 and links only
  system frameworks (Metal, Accelerate, Foundation), i.e. it statically embeds
  arm64 ggml and Metal. All 22 of them are dead weight on Apple Silicon.
- **MLX (323 MB) is only needed for MLX-format models.** GGUF runs through
  `llama-server`. Verified: pull and generate both succeed with
  `mlx_metal_v3/` and `mlx_metal_v4/` removed. **This makes the shipped model
  manifest GGUF-only by construction** — adding an MLX-format model would require
  restoring those directories.
- **`ollama` itself ships universal** and thins 68 MB → 31 MB.

Net: 404 MB → 43 MB (`ollama` + `llama-server`).

### Model pulls need no `PATH`

`POST /api/pull` over HTTP works against our own server, so the backend no longer
needs to `subprocess`-exec an `ollama` binary found on `PATH`. That removes the
reason the launchd plist injects `@@OLLAMA_BIN_DIR@@`, and it is what makes model
provisioning work from a GUI-launched process with a minimal environment.

## Post-install components

Anything optional is fetched after installation, on the user's say-so, through
`app/services/components.py` and `GET|POST|DELETE /setup/components`. That
catalogue is also the single source of truth for model names, which previously
appeared in `config.py`, `.env.example`, three install scripts,
`docker-compose.yml`, `start.sh` and the README with nothing keeping them
consistent.

Two reasons, and the second is the binding one.

**Weight.** A bundle carrying every model would be tens of gigabytes and most
users need none of them.

**Licensing.** Luminary is Apache-2.0, so copyleft code cannot travel inside the
installer. Two dependencies are affected:

- **ffmpeg** — the static builds that carry x264/x265 are GPL. Never bundled;
  installed on request into `DATA_DIR/bin`.
- **PyAV (`av`)**, pulled in by `faster-whisper`. Its binary wheels ship a full
  FFmpeg library set **including `libx264` and `libx265`**, both
  GPL-2.0-or-later. Shipping `av` inside an Apache-2.0 installer is therefore a
  licence conflict, and it is currently in the `full` dependency group that the
  bundle installs. **Open decision:** either move audio transcription to a
  post-install component, or accept relicensing the distributed artifact.

Because the licence travels with the download, `licence` is a field on every
catalogue entry and is shown before an install starts rather than buried in a
notices file. `test_setup_and_paths.py` asserts that any copyleft entry is
marked as not distributed.

Tools are resolved by `resolve_tool()`, which searches `DATA_DIR/bin` before
`PATH` — a GUI-launched process gets a minimal environment and cannot rely on a
user's shell.

## Constraints

- **Apple Silicon, macOS 14+.** Not a preference: `lancedb` publishes no macOS
  x86_64 wheel and `onnxruntime` cp313 ships only `macosx_14_0_arm64`.
- **`torch` stays in v1.** `optimum` declares `torch>=1.11` unconditionally, as do
  `sentence-transformers` and `gliner`, so "move to ONNX via optimum" *increases*
  size. Removing torch means replacing all of them, and the win is all-or-nothing
  because migrating only the embedder still leaves `gliner` pinning torch.
  Tracked separately, GLiNER-first, eval-gated.
- **Model weights are not bundled.** ~3.5 GB of encoder and LLM weights are
  fetched on first run behind a progress UI. Shipping them in the DMG is not
  viable.
- **`ffmpeg` is still an unbundled external dependency.** `transcribe.py` and
  `main.py` both `shutil.which("ffmpeg")`, and YouTube ingestion needs it to
  produce WAV. A bundled app cannot tell a user to `brew install ffmpeg`, so
  either ffmpeg ships in `Resources/` or MP4/YouTube ingestion must be gated off
  in the UI. Open item.
