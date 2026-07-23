#!/usr/bin/env bash
# install.sh — idempotent one-command install for Luminary.
#
# Installs uv, Node, Ollama (per-platform), pulls the default chat LLM (and an
# optional vision model on request), syncs backend deps (public profile), builds
# the frontend SPA. Safe to re-run.
#
# Usage:   bash scripts/install.sh
# Then:    make start

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CHAT_MODEL="${LUMINARY_CHAT_MODEL:-llama3.2}"
VISION_MODEL="${LUMINARY_VISION_MODEL:-}"

_info()  { printf '\033[0;36m[install]\033[0m %s\n' "$*"; }
_warn()  { printf '\033[0;33m[install]\033[0m %s\n' "$*"; }
_err()   { printf '\033[0;31m[install]\033[0m %s\n' "$*" >&2; }
_have()  { command -v "$1" >/dev/null 2>&1; }

OS="$(uname -s)"
ARCH="$(uname -m)"
_info "Platform: $OS/$ARCH"

case "$OS" in
    Darwin) ;;
    Linux)  ;;
    *) _err "Unsupported OS: $OS. Use Docker (see docs)."; exit 1 ;;
esac

# Intel Macs have no native lancedb wheel (only macOS arm64 is published), so the
# backend dep sync can't succeed here. Fail fast with Docker guidance instead of
# dying later on a cryptic uv resolver error.
if [ "$OS" = "Darwin" ] && [ "$ARCH" = "x86_64" ]; then
    _err "Native install isn't supported on Intel Macs (x86_64) — lancedb has no macOS x86_64 wheel."
    _err "Run via Docker instead:  docker compose --profile ai up   (or: make docker-run)"
    exit 1
fi

# ---------------------------------------------------------------------------
# uv — Python package + project manager
# ---------------------------------------------------------------------------
if _have uv; then
    _info "uv present: $(uv --version)"
else
    _info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # uv installs to ~/.local/bin or ~/.cargo/bin depending on platform
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    _have uv || { _err "uv install completed but binary not on PATH. Open a new shell and re-run."; exit 1; }
fi

# ---------------------------------------------------------------------------
# Node — required for the frontend build
# ---------------------------------------------------------------------------
if _have node; then
    NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
    if [ "$NODE_MAJOR" -lt 20 ]; then
        _warn "Node $NODE_MAJOR detected; frontend build needs >=20. Upgrade with your version manager (fnm/nvm/asdf) or 'brew upgrade node'."
        exit 1
    fi
    _info "node present: $(node --version)"
else
    if [ "$OS" = "Darwin" ] && _have brew; then
        _info "Installing node via brew..."
        brew install node
    elif _have fnm; then
        _info "Installing node 20 via fnm..."
        fnm install 20 && fnm use 20
    else
        _err "Node not found and no brew/fnm available. Install Node 20+ (https://nodejs.org/) and re-run."
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Ollama — local LLM runtime
# ---------------------------------------------------------------------------
if _have ollama; then
    _info "ollama present: $(ollama --version 2>/dev/null | head -1)"
else
    if [ "$OS" = "Darwin" ] && _have brew; then
        _info "Installing ollama via brew..."
        brew install ollama
    elif [ "$OS" = "Linux" ]; then
        _info "Installing ollama via official script..."
        curl -fsSL https://ollama.com/install.sh | sh
    else
        _err "Could not auto-install ollama. Install from https://ollama.com/ and re-run."
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Performance profile — sizes Ollama residency/parallelism + vision concurrency.
# public=1/1/1 (~8GB), standard=2/2/2 (~16GB), performance=2/4/4 (bigger box).
# ---------------------------------------------------------------------------
PROFILE="${LUMINARY_PROFILE:-}"
if [ -z "$PROFILE" ] && [ -t 0 ]; then
    printf '\033[0;36m[install]\033[0m Performance profile? [1] public/8GB  [2] standard/16GB (default)  [3] performance : '
    read -r _p || _p=""
    case "$_p" in
        1|public)      PROFILE="public" ;;
        3|performance) PROFILE="performance" ;;
        *)             PROFILE="standard" ;;
    esac
fi
PROFILE="${PROFILE:-standard}"
case "$PROFILE" in
    public)      OLLAMA_MAX_LOADED_MODELS=1; OLLAMA_NUM_PARALLEL=1; VISION_CONCURRENCY=1 ;;
    performance) OLLAMA_MAX_LOADED_MODELS=2; OLLAMA_NUM_PARALLEL=4; VISION_CONCURRENCY=4 ;;
    *)           OLLAMA_MAX_LOADED_MODELS=2; OLLAMA_NUM_PARALLEL=2; VISION_CONCURRENCY=2 ;;
esac
export OLLAMA_MAX_LOADED_MODELS OLLAMA_NUM_PARALLEL
_info "Profile '$PROFILE': OLLAMA_MAX_LOADED_MODELS=$OLLAMA_MAX_LOADED_MODELS OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL ENRICHMENT_VISION_CONCURRENCY=$VISION_CONCURRENCY"

# Persist the app-side knob so the backend (which reads backend/.env) picks it up.
ENV_FILE="$REPO_ROOT/backend/.env"
touch "$ENV_FILE"
if grep -q '^ENRICHMENT_VISION_CONCURRENCY=' "$ENV_FILE" 2>/dev/null; then
    _tmp="$(mktemp)"
    grep -v '^ENRICHMENT_VISION_CONCURRENCY=' "$ENV_FILE" > "$_tmp" && mv "$_tmp" "$ENV_FILE"
fi
printf 'ENRICHMENT_VISION_CONCURRENCY=%s\n' "$VISION_CONCURRENCY" >> "$ENV_FILE"

# Start ollama if it's not already serving.
if ! curl -sf --max-time 2 http://localhost:11434/api/version >/dev/null 2>&1; then
    _info "Starting ollama server in background (profile env applied)..."
    if [ "$OS" = "Darwin" ] && _have brew; then
        brew services start ollama >/dev/null 2>&1 || nohup ollama serve >/tmp/ollama.log 2>&1 &
    else
        nohup ollama serve >/tmp/ollama.log 2>&1 &
    fi
    for i in $(seq 1 20); do
        sleep 1
        curl -sf --max-time 2 http://localhost:11434/api/version >/dev/null 2>&1 && break
        [ "$i" -eq 20 ] && { _err "ollama server didn't come up; check /tmp/ollama.log"; exit 1; }
    done
    # brew services / launchd do not inherit our exported env; warn if that path ran.
    if [ "$OS" = "Darwin" ] && _have brew && pgrep -f "Ollama" >/dev/null 2>&1; then
        _warn "If Ollama is managed by brew services, apply the profile with:"
        _warn "  launchctl setenv OLLAMA_MAX_LOADED_MODELS $OLLAMA_MAX_LOADED_MODELS && launchctl setenv OLLAMA_NUM_PARALLEL $OLLAMA_NUM_PARALLEL && brew services restart ollama"
    fi
else
    _warn "Ollama already running — restart it to apply the profile:"
    _warn "  OLLAMA_MAX_LOADED_MODELS=$OLLAMA_MAX_LOADED_MODELS OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL ollama serve   (after stopping the current server)"
fi

# Pull models only if not already cached.
_pulled() { ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$1"; }

# Optional vision model (powers image/figure analysis). Not prompted for — the
# install stays non-interactive and the closing banner tells the user how to add
# it later. Set LUMINARY_VISION_MODEL to pull one during install.
for model in "$CHAT_MODEL" "$VISION_MODEL"; do
    [ -z "$model" ] && continue
    if _pulled "$model" || _pulled "${model}:latest"; then
        _info "Model already pulled: $model"
    else
        _info "Pulling $model (this can take several minutes)..."
        ollama pull "$model"
    fi
done


# ---------------------------------------------------------------------------
# Backend deps — public profile (no labs/dev groups)
# ---------------------------------------------------------------------------
_info "Syncing backend deps (public profile)..."
(cd backend && uv sync --no-default-groups)

# ---------------------------------------------------------------------------
# Frontend build — public tier, /api base
# ---------------------------------------------------------------------------
if [ ! -d frontend/node_modules ] \
    || [ frontend/package-lock.json -nt frontend/node_modules/.package-lock.json ] 2>/dev/null; then
    _info "Installing frontend deps..."
    (cd frontend && npm ci)
fi

_info "Building production SPA..."
make build

cat <<'EOF'

[install] Done.

  Next:  make start
  Open:  http://localhost:7820

  Optional: image/figure analysis needs a vision model (~6GB download).
  Add it any time with:  ollama pull qwen2.5vl:7b

EOF
