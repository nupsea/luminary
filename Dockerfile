# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1 — Build the frontend SPA
# ---------------------------------------------------------------------------
FROM node:22-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Copy the surface manifest (server.fs.allow opens repo root; vite resolves ../../../surface-manifest.json from frontend/)
COPY surface-manifest.json /surface-manifest.json

# studyPrinciples.ts imports ../../../src-tauri/boot/principles.json -- one
# source shared with the Tauri boot screen, which can only read a file beside
# it. Missing here, the frontend build fails outright, which makes this the
# one thing that breaks docker-run/docker-compose entirely (the Intel Mac and
# any-unsupported-host fallback) rather than a feature silently not working.
COPY src-tauri/boot/principles.json /src-tauri/boot/principles.json

COPY frontend/ .
RUN VITE_LUMINARY_MODE=public VITE_API_BASE=/api npm run build

# ---------------------------------------------------------------------------
# Stage 2 — Production backend (serves the SPA too)
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS backend

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install public-profile deps first (layer cache)
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-default-groups --no-install-project

# Audio/video ingestion (MP4, YouTube), off by default.
#
# ffmpeg and faster-whisper's PyAV carry x264/x265, which are GPL-2.0-or-later,
# and Luminary is Apache-2.0 -- so neither may travel inside anything the
# project distributes. Nothing here breaks that: this image is built on the
# user's own machine (`docker-compose.yml` uses `build:`, and no workflow
# publishes an image), so opting in installs GPL code from upstream by the
# user's own action, exactly as `apt install ffmpeg` would.
#
# One flag does the whole path deliberately. ffmpeg alone leaves the downloader
# and the transcriber missing, and the user hits a second wall with a worse
# message -- the failure mode `_media_missing_message` exists to prevent.
# `media` and not `full`: `full` also carries the tree-sitter grammars, and
# `code_parsing` is a full-mode surface this image does not serve.
ARG WITH_MEDIA=0
RUN if [ "$WITH_MEDIA" = "1" ]; then \
      apt-get update && \
      apt-get install -y --no-install-recommends ffmpeg && \
      rm -rf /var/lib/apt/lists/* && \
      uv sync --frozen --no-default-groups --group media --no-install-project; \
    fi

# Copy app code and the surface manifest.
# surface_manifest.py resolves Path(__file__).parents[2]/surface-manifest.json;
# in this image __file__=/app/app/surface_manifest.py so parents[2]=/
COPY backend/ .
COPY surface-manifest.json /surface-manifest.json

# db_init.py's alembic_ini() resolves app_root()/"backend"/"alembic.ini" -- same
# parents[2]=/ as above, so it wants /backend/alembic.ini, not the /alembic.ini
# `COPY backend/ .` already placed above. Without this the app crashed on every
# boot: "No 'script_location' key found in configuration." alembic/ itself
# (env.py, versions/) has to come along too -- script_location is relative to
# alembic.ini's own directory, not app_root().
COPY backend/alembic.ini /backend/alembic.ini
COPY backend/alembic/ /backend/alembic/

# app_version() reads pyproject_path() = /backend/pyproject.toml (same
# app_root()=/ resolution as above) to report the shipped version; without
# this it caught the FileNotFoundError and silently reported "0.0.0" on
# every /health call instead of crashing, which is why this one shipped
# unnoticed for however long docker-run has existed.
COPY backend/pyproject.toml /backend/pyproject.toml

# Copy frontend build artefacts into the path the server resolves.
# serve_spa uses Path(__file__).parents[2]/"frontend"/"dist"; here
# __file__=/app/app/main.py so parents[2]=/ -> dist must live at /frontend/dist
# (same reason surface-manifest.json is placed at / above).
COPY --from=frontend-build /frontend/dist /frontend/dist

# The venv's bin on PATH, because `resolve_tool` finds tools with
# `shutil.which`. `uv run` used to put it there; running the interpreter
# directly does not, so console scripts installed into the venv (yt-dlp) were
# present on disk and invisible to the app -- a YouTube ingest failed saying
# yt-dlp was missing while `/app/.venv/bin/yt-dlp --version` answered fine.
ENV PATH="/app/.venv/bin:${PATH}" \
    LUMINARY_MODE=public \
    DATA_DIR=/data \
    PORT=7820

EXPOSE 7820

# DATA_DIR is a volume mount — create it so it exists even without a volume
RUN mkdir -p /data

# The venv interpreter directly, never `uv run`. `uv run` resolves the project
# before executing, and it resolves DEFAULT groups -- so every container start
# downloaded and installed 46 packages (av, ctranslate2, faster-whisper,
# yt-dlp, arize-phoenix, ruff, pytest) over the network, into the image that
# had just been built without them. Three things broke at once: the image's
# dependency curation was undone at runtime, a local-first app needed the
# network to boot, and the GPL components the licence carve-out exists to keep
# out of distribution were installed automatically anyway.
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7820"]
