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

COPY frontend/ .
RUN VITE_SURFACE_TIER=public VITE_API_BASE=/api npm run build

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

# Copy app code and the surface manifest.
# surface_manifest.py resolves Path(__file__).parents[2]/surface-manifest.json;
# in this image __file__=/app/app/surface_manifest.py so parents[2]=/
COPY backend/ .
COPY surface-manifest.json /surface-manifest.json

# Copy frontend build artefacts into the path the server resolves.
# serve_spa uses Path(__file__).parents[2]/"frontend"/"dist"; here
# __file__=/app/app/main.py so parents[2]=/ -> dist must live at /frontend/dist
# (same reason surface-manifest.json is placed at / above).
COPY --from=frontend-build /frontend/dist /frontend/dist

ENV LUMINARY_MODE=prod \
    LUMINARY_SURFACE_TIER=public \
    DATA_DIR=/data \
    PORT=7820

EXPOSE 7820

# DATA_DIR is a volume mount — create it so it exists even without a volume
RUN mkdir -p /data

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7820"]
