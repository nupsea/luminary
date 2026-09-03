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

# Resolved after the profile is known: on a host that may keep only ONE model
# loaded, the chat model has to be the one that also reads figures, or vision has
# no model that machine can hold. See PUBLIC_GENERALIST below.
CHAT_MODEL="${LUMINARY_CHAT_MODEL:-}"
VISION_MODEL="${LUMINARY_VISION_MODEL:-}"

# One model, every role, on an 8-16GB laptop. Must stay equal to
# `model_registry.GENERALIST_PREFERENCE[0]`; `tests/test_installer_models.py`
# fails if the two drift, because the backend resolves to that model whether or
# not this pulled it.
PUBLIC_GENERALIST="qwen3.5:4b"
# The dedicated reader, pulled where the profile can hold a second model. Left
# optional before, which put the install and the backend in disagreement: the
# backend resolves vision to this on a host with room whether or not it is on
# disk, and figure analysis then fails quietly.
# The strongest text model, pulled only on `performance` -- 9.67GB resident, and
# it does not read figures, so it is always a second model alongside the reader.
LARGE_TEXT_MODEL="qwen2.5:14b-instruct"
# The band is a policy choice; this is a measurement. The backend keeps a
# resident set to half of RAM, and this model plus the generalist is 12.88GB, so
# the pair needs 25.76GB -- 25GB fails and 26GB fits. Below this the installer
# would download 9.67GB the backend then refuses to load.
# test_installer_models.py recomputes this from the registry and fails on drift.
LARGE_TEXT_MIN_RAM_GB=26
# Used where two models can be resident. Same id as the generalist today: the
# structural matrix put it ahead of llama3.2 on every metric it measured, and
# llama3.2 held the default only on an HHEM comparison this repo ruled
# inadmissible for choosing a model.
DEFAULT_CHAT_MODEL="qwen3.5:4b"

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

# Every install path below assumes curl (uv's own installer, the Node tarball
# fetch, ollama's installer script). Unlike uv/node/ollama themselves this had
# no _have guard, so a bare container -- no desktop convenience layer installed
# curl for it -- died on a raw "command not found" instead of this script's own
# error convention. Measured on stock ubuntu:24.04 and debian:bookworm images.
_have curl || { _err "curl is required and not on PATH. Install it and re-run."; exit 1; }
# `make` is checked HERE rather than where the SPA build uses it. The guard at
# the build step already existed and still let a Debian/Fedora/Arch adopter sit
# through node, uv, ~1.6GB of Python wheels, npm and the model pull before being
# told to install a prerequisite and start again. Measured on debian:bookworm-slim:
# the run reached "Building production SPA" and failed there after ten minutes.
_have make || { _err "make is required and not on PATH. Install it (e.g. build-essential/base-devel) and re-run."; exit 1; }

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
NODE_MIN=20

# Ubuntu's apt only carries Node 18, so "install Node yourself" was a dead end
# on the platform the from-source path targets. Fetch the official LTS build
# into ~/.local, the way uv installs itself -- no sudo, no apt repo, no
# version manager.
_install_node_linux() {
    local arch tarball url dest
    case "$ARCH" in
        x86_64)          arch="x64" ;;
        aarch64|arm64)   arch="arm64" ;;
        *) _err "No official Node build for $ARCH. Install Node $NODE_MIN+ manually and re-run."; return 1 ;;
    esac
    tarball="$(curl -fsSL https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt \
        | grep -oE "node-v[0-9.]+-linux-${arch}\.tar\.gz" | head -1)" || true
    if [ -z "$tarball" ]; then
        _err "Could not resolve a Node LTS download. Install Node $NODE_MIN+ manually and re-run."
        return 1
    fi
    url="https://nodejs.org/dist/latest-v22.x/${tarball}"
    dest="$HOME/.local/share/luminary/node"
    _info "Installing ${tarball%-linux-*} to $dest ..."
    mkdir -p "$dest" "$HOME/.local/bin"
    curl -fsSL "$url" | tar -xz -C "$dest" --strip-components=1
    ln -sf "$dest/bin/node" "$HOME/.local/bin/node"
    ln -sf "$dest/bin/npm" "$HOME/.local/bin/npm"
    ln -sf "$dest/bin/npx" "$HOME/.local/bin/npx"
    export PATH="$HOME/.local/bin:$PATH"
    _have node || { _err "Node installed to $dest but not on PATH."; return 1; }
}

_node_too_old() {
    [ "$(node -p 'process.versions.node.split(".")[0]')" -lt "$NODE_MIN" ]
}

if _have node && ! _node_too_old; then
    _info "node present: $(node --version)"
elif [ "$OS" = "Darwin" ] && _have brew; then
    _info "Installing node via brew..."
    brew install node
elif _have fnm; then
    _info "Installing node $NODE_MIN via fnm..."
    fnm install "$NODE_MIN" && fnm use "$NODE_MIN"
elif [ "$OS" = "Linux" ]; then
    _have node && _warn "Node $(node --version) is older than $NODE_MIN; installing a private LTS build."
    _install_node_linux || exit 1
    _info "node ready: $(node --version)"
else
    _err "Node not found and no brew/fnm available. Install Node $NODE_MIN+ (https://nodejs.org/) and re-run."
    exit 1
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
        # Ollama's installer extracts a zstd archive, and a stock Ubuntu image
        # has no zstd -- it fails with "requires zstd for extraction" after the
        # download. Get it in place first.
        if ! _have zstd; then
            _info "Installing zstd (required by the ollama installer)..."
            if [ "$(id -u)" = "0" ]; then
                _SUDO=""
            elif _have sudo; then
                _SUDO="sudo"
            else
                _err "zstd is missing and neither root nor sudo is available."
                _err "Install it, then re-run:  apt-get install -y zstd   (or your package manager's equivalent)"
                exit 1
            fi
            if _have apt-get; then
                $_SUDO apt-get update -qq && $_SUDO apt-get install -y -qq zstd
            elif _have dnf; then
                $_SUDO dnf install -y zstd
            elif _have pacman; then
                $_SUDO pacman -S --noconfirm zstd
            else
                _err "Could not install zstd automatically. Install it and re-run."
                exit 1
            fi
        fi
        _info "Installing ollama via official script..."
        curl -fsSL https://ollama.com/install.sh | sh
    else
        _err "Could not auto-install ollama. Install from https://ollama.com/ and re-run."
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Performance profile — sizes Ollama residency/parallelism + vision concurrency.
# standard=2/2/2 (16GB floor, up to 24GB), performance=2/4/4 (over 24GB).
# ---------------------------------------------------------------------------
# Physical RAM in GB, 0 when unreadable. The profile is a memory decision, so
# an unknown box must not be guessed into "standard".
_mem_gb() {
    if [ "$OS" = "Darwin" ]; then
        _b="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
        echo $(( _b / 1073741824 ))
    elif [ -r /proc/meminfo ]; then
        _k="$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)"
        echo $(( _k / 1048576 ))
    else
        echo 0
    fi
}

# 16GB is the supported floor. A smaller machine still installs and runs on
# `standard`; the backend reports the mismatch rather than narrowing itself to a
# one-model profile, which is what made the experience fall flat off macOS.
# Must stay in step with `memory_profile.profile_for_ram`: two detectors that
# disagree about what machine this is are worse than one that is occasionally
# wrong.
_default_profile() {
    _gb="$(_mem_gb)"
    if [ "$_gb" -gt 24 ]; then echo "performance"
    else                       echo "standard"
    fi
}

_warn_if_under_floor() {
    _gb="$(_mem_gb)"
    if [ "$_gb" -ne 0 ] && [ "$_gb" -lt 16 ]; then
        _warn "This machine reports ${_gb}GB. Luminary is tuned for 16GB and up:"
        _warn "ingestion, chat and flashcard generation will be slower here."
    fi
}

PROFILE="${LUMINARY_PROFILE:-}"
# `low` and `public` named the retired one-model profile. Both are accepted and
# resolve to `standard`, matching `memory_profile._LEGACY_ALIASES`, so an
# existing .env and any script passing the old name keep working.
case "$PROFILE" in
    low|public) PROFILE="standard" ;;
esac
case "${PROFILE:-standard}" in
    standard|performance) ;;
    *)
        _err "LUMINARY_PROFILE='$PROFILE' is not one of: standard, performance (low/public map to standard)."
        _err "It would be written to backend/.env, where the backend rejects it and"
        _err "re-sizes from host RAM -- so the installer and the app would disagree."
        exit 1
        ;;
esac
if [ -z "$PROFILE" ]; then
    _suggested="$(_default_profile)"
    if [ -t 0 ]; then
        printf '\033[0;36m[install]\033[0m Performance profile? [1] standard/16-24GB  [2] performance/over 24GB  (default: %s, sized from %sGB RAM) : ' "$_suggested" "$(_mem_gb)"
        read -r _p || _p=""
        case "$_p" in
            1|standard)    PROFILE="standard" ;;
            2|performance) PROFILE="performance" ;;
            *)             PROFILE="$_suggested" ;;
        esac
    else
        # Non-interactive (CI, curl | sh): size it rather than assuming.
        PROFILE="$_suggested"
    fi
fi
case "$PROFILE" in
    performance) OLLAMA_MAX_LOADED_MODELS=2; OLLAMA_NUM_PARALLEL=4; VISION_CONCURRENCY=4 ;;
    *)           OLLAMA_MAX_LOADED_MODELS=2; OLLAMA_NUM_PARALLEL=2; VISION_CONCURRENCY=2 ;;
esac
# Ollama's own defaults are not sized for a laptop: the prompt cache is allowed
# 8192MB (more than a small machine has in total) and models unload after 5
# minutes, paying a full reload on the next question. The backend cannot set
# either -- LiteLLM's `ollama/` completion path folds keep_alive into `options`,
# where Ollama rejects it -- so they belong wherever the server is started.
OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"
LLAMA_ARG_CACHE_RAM="${LLAMA_ARG_CACHE_RAM:-512}"
export OLLAMA_MAX_LOADED_MODELS OLLAMA_NUM_PARALLEL OLLAMA_KEEP_ALIVE LLAMA_ARG_CACHE_RAM
_warn_if_under_floor
_info "Profile '$PROFILE': OLLAMA_MAX_LOADED_MODELS=$OLLAMA_MAX_LOADED_MODELS OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL ENRICHMENT_VISION_CONCURRENCY=$VISION_CONCURRENCY"

# The chat model follows the profile. The one-model band is retired, but the
# branch stays: OLLAMA_MAX_LOADED_MODELS is overridable, and a machine held to
# one slot still needs a model that can read a figure. Formerly, on `public`,
# the runtime kept one
# model loaded. Pulling a text-only model there left the vision role with nothing
# the machine could hold: the backend would resolve it to a second model, and
# OLLAMA_MAX_LOADED_MODELS=1 means loading it evicts the one answering questions.
# `qwen3.5:4b` reads figures at 3.21GB resident -- the same as its text footprint.
if [ -z "$CHAT_MODEL" ]; then
    if [ "$OLLAMA_MAX_LOADED_MODELS" -le 1 ]; then
        CHAT_MODEL="$PUBLIC_GENERALIST"
        _info "Profile '$PROFILE' keeps one model loaded: using $CHAT_MODEL for chat AND figures"
    else
        # `performance` is the only band with room for a text model that cannot
        # read figures. Everywhere else one model does both, which is what the
        # backend resolves to -- pulling anything else downloads a model that
        # never loads.
        if [ "$PROFILE" = "performance" ] && [ "$(_mem_gb)" -ge "$LARGE_TEXT_MIN_RAM_GB" ]; then
            CHAT_MODEL="$LARGE_TEXT_MODEL"
        else
            CHAT_MODEL="$DEFAULT_CHAT_MODEL"
        fi
    fi
fi

# Outside the block above on purpose. While it was nested inside
# `if [ -z "$CHAT_MODEL" ]`, setting LUMINARY_CHAT_MODEL alone skipped it, and a
# `performance` host with room for a reader pulled none -- figures then failed
# quietly, which is the exact mode this profile exists to avoid.
if [ -z "$VISION_MODEL" ] && [ "$OLLAMA_MAX_LOADED_MODELS" -gt 1 ] \
   && [ "$CHAT_MODEL" != "$PUBLIC_GENERALIST" ]; then
    VISION_MODEL="$PUBLIC_GENERALIST"
fi
_info "Profile '$PROFILE': $CHAT_MODEL for text${VISION_MODEL:+, $VISION_MODEL for figures}"

# Persist the app-side knobs so the backend (which reads backend/.env) picks them
# up. OLLAMA_NUM_PARALLEL goes in too, not just the server env: the backend
# sizes its enrichment concurrency from it.
ENV_FILE="$REPO_ROOT/backend/.env"
touch "$ENV_FILE"
_upsert_env() {
    if grep -q "^$1=" "$ENV_FILE" 2>/dev/null; then
        _tmp="$(mktemp)"
        grep -v "^$1=" "$ENV_FILE" > "$_tmp" && mv "$_tmp" "$ENV_FILE"
    fi
    printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE"
}
_upsert_env ENRICHMENT_VISION_CONCURRENCY "$VISION_CONCURRENCY"
_upsert_env OLLAMA_NUM_PARALLEL "$OLLAMA_NUM_PARALLEL"
# The profile itself, in the backend's vocabulary. Without it the backend sized
# its own profile from host RAM and could disagree with the one chosen here: pick
# `public` on a 32GB machine and the backend would resolve chat and vision to two
# models this install never pulled. `low` is the canonical name; `public` is read
# as a legacy alias, so writing the canonical one keeps old .env files working
# without adding a second spelling.
case "$PROFILE" in
    public) _upsert_env LUMINARY_MEMORY_PROFILE "low" ;;
    *)      _upsert_env LUMINARY_MEMORY_PROFILE "$PROFILE" ;;
esac
# The models this installer actually pulled. Leaving them unset let the backend
# resolve a model that is not on disk, which fails at the first question instead
# of here; it also left `start.sh` with nothing to read, so its "model isn't
# pulled" pre-flight silently checked nothing on the primary install path.
_upsert_env LITELLM_DEFAULT_MODEL "ollama/$CHAT_MODEL"
_upsert_env VISION_MODEL "ollama/${VISION_MODEL:-$CHAT_MODEL}"

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
        _warn "  launchctl setenv OLLAMA_MAX_LOADED_MODELS $OLLAMA_MAX_LOADED_MODELS && launchctl setenv OLLAMA_NUM_PARALLEL $OLLAMA_NUM_PARALLEL && launchctl setenv OLLAMA_KEEP_ALIVE $OLLAMA_KEEP_ALIVE && launchctl setenv LLAMA_ARG_CACHE_RAM $LLAMA_ARG_CACHE_RAM && brew services restart ollama"
    fi
else
    _warn "Ollama already running — restart it to apply the profile:"
    _warn "  OLLAMA_MAX_LOADED_MODELS=$OLLAMA_MAX_LOADED_MODELS OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL OLLAMA_KEEP_ALIVE=$OLLAMA_KEEP_ALIVE LLAMA_ARG_CACHE_RAM=$LLAMA_ARG_CACHE_RAM ollama serve   (after stopping the current server)"
fi

# Pull models only if not already cached.
_pulled() { ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$1"; }

# The vision model is pulled only where the profile can keep a second model
# loaded; on the single-model profile the chat model reads figures itself.
# Set LUMINARY_VISION_MODEL to override which one.
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
# `full` adds yt-dlp and the tree-sitter grammars. The article path
# (trafilatura, cloudscraper) moved to base dependencies, because web_ingest is
# a `public` surface and the Docker image installs base only -- it was shipping
# without the libraries its own manifest advertised.
(cd backend && uv sync --no-default-groups --group full)

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

if [ "$OLLAMA_MAX_LOADED_MODELS" -le 1 ]; then
cat <<EOF

[install] Done.

  Next:  make start
  Open:  http://localhost:7820

  $CHAT_MODEL answers questions and reads figures, so image analysis works
  already. This profile keeps one model loaded: adding a second one does not
  give you both, it evicts the first.

EOF
else
cat <<EOF

[install] Done.

  Next:  make start
  Open:  http://localhost:7820

  Models pulled: $CHAT_MODEL${VISION_MODEL:+ and $VISION_MODEL}.
  ${VISION_MODEL:-$CHAT_MODEL} reads figures.

EOF
fi
