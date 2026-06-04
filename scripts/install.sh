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

# Start ollama if it's not already serving.
if ! curl -sf --max-time 2 http://localhost:11434/api/version >/dev/null 2>&1; then
    _info "Starting ollama server in background..."
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
fi

# Pull models only if not already cached.
_pulled() { ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$1"; }

# Optional vision model (labs-gated; powers image/figure analysis). Skipped by
# default — large download. Set LUMINARY_VISION_MODEL, answer the prompt, or add
# it later with: ollama pull llava:7b
if [ -z "$VISION_MODEL" ] && [ -t 0 ]; then
    printf '\033[0;36m[install]\033[0m Install the optional vision model (llava:7b, ~4.7GB) for image/figure analysis? [y/N] '
    read -r _ans
    case "$_ans" in
        y|Y|yes|YES) VISION_MODEL="llava:7b" ;;
    esac
fi

for model in "$CHAT_MODEL" "$VISION_MODEL"; do
    [ -z "$model" ] && continue
    if _pulled "$model" || _pulled "${model}:latest"; then
        _info "Model already pulled: $model"
    else
        _info "Pulling $model (this can take several minutes)..."
        ollama pull "$model"
    fi
done

[ -z "$VISION_MODEL" ] && _info "Skipping vision model. Enable image/figure analysis later with: ollama pull llava:7b"

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

EOF
