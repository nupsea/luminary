#!/usr/bin/env bash
# uninstall.sh — undo `make install` / `make install-dev` for this checkout.
#
# Removes what lives in the checkout (backend/.venv, frontend/node_modules,
# frontend/dist, the installer's keys in backend/.env) and whatever install.sh
# recorded in .install-manifest as installed by it. A tool that was already on
# the machine is never recorded, so it is never removed. The library
# (.luminary/) is kept unless --purge-data.
#
# Usage: bash scripts/uninstall.sh [--dry-run] [--yes] [--purge-data]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/.install-manifest"
BACKEND_PORT=7820

# Keys install.sh writes into backend/.env; any other line there is the user's.
# test_uninstall.py fails if this drifts from install.sh's _upsert_env calls.
INSTALLER_ENV_KEYS="ENRICHMENT_VISION_CONCURRENCY OLLAMA_NUM_PARALLEL LUMINARY_MEMORY_PROFILE LITELLM_DEFAULT_MODEL VISION_MODEL"

DRY_RUN=0
YES=0
PURGE_DATA=0
for _arg in "$@"; do
    case "$_arg" in
        --dry-run)    DRY_RUN=1 ;;
        --yes|-y)     YES=1 ;;
        --purge-data) PURGE_DATA=1 ;;
        *) printf 'usage: bash scripts/uninstall.sh [--dry-run] [--yes] [--purge-data]\n' >&2; exit 2 ;;
    esac
done

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

_info() { printf '\033[0;36m[uninstall]\033[0m %s\n' "$*"; }
_warn() { printf '\033[0;33m[uninstall]\033[0m %s\n' "$*"; }
_err()  { printf '\033[0;31m[uninstall]\033[0m %s\n' "$*" >&2; }
_have() { command -v "$1" >/dev/null 2>&1; }
_size() { du -sh "$1" 2>/dev/null | cut -f1; }
_recorded() { [ -f "$MANIFEST" ] && grep -qxF "$1" "$MANIFEST"; }

# Deleting the venv under a running backend leaves it half-dead holding the DB.
if _have lsof && lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    _err "Something is listening on :$BACKEND_PORT -- stop Luminary first (make clean), then re-run."
    exit 1
fi

# ---------------------------------------------------------------------------
# Actions. Each step runs twice: MODE=plan lists it, MODE=run performs it.
# ---------------------------------------------------------------------------
MODE=plan
STEPS=0
_act() {
    local desc="$1"; shift
    STEPS=$((STEPS + 1))
    if [ "$MODE" = plan ]; then
        printf '  - %s\n' "$desc"
    else
        _info "$desc"
        "$@" || _warn "  failed; continuing"
    fi
}

_strip_installer_env() {
    local env_file="$REPO_ROOT/backend/.env" tmp key
    tmp="$(mktemp)"
    cp "$env_file" "$tmp"
    for key in $INSTALLER_ENV_KEYS; do
        grep -v "^$key=" "$tmp" > "$tmp.next" || true
        mv "$tmp.next" "$tmp"
    done
    if grep -q '[^[:space:]]' "$tmp"; then
        mv "$tmp" "$env_file"
    else
        rm -f "$tmp" "$env_file"
    fi
}

_has_installer_env() {
    local key
    for key in $INSTALLER_ENV_KEYS; do
        grep -q "^$key=" "$REPO_ROOT/backend/.env" 2>/dev/null && return 0
    done
    return 1
}

_python_caches() {
    find "$REPO_ROOT/backend" -path "$REPO_ROOT/backend/.venv" -prune -o \
        \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -type d -print -prune
}
_remove_python_caches() { _python_caches | while IFS= read -r d; do rm -rf "$d"; done; }

_remove_model() { ollama rm "$1" >/dev/null; }

_remove_brew_ollama() {
    brew services stop ollama >/dev/null 2>&1 || true
    brew uninstall ollama
}

_remove_local_node() {
    local link
    for link in node npm npx; do
        case "$(readlink "$HOME/.local/bin/$link" 2>/dev/null)" in
            "$HOME/.local/share/luminary/node/"*) rm -f "$HOME/.local/bin/$link" ;;
        esac
    done
    rm -rf "$HOME/.local/share/luminary/node"
}

# uv's documented uninstall, minus `uv tool dir`: tools installed there since
# are the user's, not ours.
_remove_uv() {
    uv cache clean >/dev/null 2>&1 || true
    rm -rf "$(uv python dir)"
    rm -f "$HOME/.local/bin/uv" "$HOME/.local/bin/uvx" "$HOME/.cargo/bin/uv" "$HOME/.cargo/bin/uvx"
}

_steps() {
    local dir model
    for dir in backend/.venv frontend/node_modules frontend/dist; do
        if [ -e "$REPO_ROOT/$dir" ]; then
            _act "Remove $dir ($(_size "$REPO_ROOT/$dir"))" rm -rf "${REPO_ROOT:?}/$dir"
        fi
    done
    if [ -n "$(_python_caches | head -1)" ]; then
        _act "Remove Python caches under backend/ (__pycache__, .pytest_cache, .ruff_cache)" _remove_python_caches
    fi
    if _has_installer_env; then
        _act "Remove the installer's settings from backend/.env (other lines are kept)" _strip_installer_env
    fi
    if [ "$PURGE_DATA" = 1 ] && [ -e "$REPO_ROOT/.luminary" ]; then
        _act "DELETE the dev library .luminary/ ($(_size "$REPO_ROOT/.luminary")): documents, notes, flashcards" \
            rm -rf "${REPO_ROOT:?}/.luminary"
    fi

    [ -f "$MANIFEST" ] || return 0
    if _have ollama; then
        while IFS= read -r model; do
            if ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qxF "$model"; then
                _act "Remove Ollama model $model (pulled by the installer)" _remove_model "$model"
            fi
        done < <(sed -n 's/^model://p' "$MANIFEST")
    fi
    if _recorded ollama:brew && _have brew; then
        _act "Uninstall Ollama (brew; models in ~/.ollama are kept)" _remove_brew_ollama
    fi
    if _recorded node:brew && _have brew; then
        _act "Uninstall Node (brew)" brew uninstall node
    fi
    if _recorded node:local && [ -d "$HOME/.local/share/luminary/node" ]; then
        _act "Remove Node from ~/.local/share/luminary/node" _remove_local_node
    fi
    if _recorded uv && _have uv; then
        _act "Uninstall uv: binary, its cache ($(_size "$(uv cache dir)")) and its Pythons" _remove_uv
    fi
    _act "Forget the install record (.install-manifest)" rm -f "$MANIFEST"
}

_steps >/dev/null
if [ "$STEPS" = 0 ]; then
    _info "Nothing to remove."
else
    printf '\nThis will:\n'
    MODE=plan; STEPS=0; _steps
    echo
fi

# Left alone, said out loud so nothing is silently orphaned.
if [ "$PURGE_DATA" = 0 ] && [ -e "$REPO_ROOT/.luminary" ]; then
    _info "Keeping the dev library at $REPO_ROOT/.luminary (pass --purge-data to delete it)."
fi
if [ ! -f "$MANIFEST" ]; then
    _info "No install record, so uv, Node, Ollama and models are left as they are."
    _info "They predate this uninstaller or were already on the machine; remove them by hand if unwanted."
fi
if _recorded ollama:script; then
    _warn "Ollama was installed by its Linux script; removing it needs root: https://github.com/ollama/ollama/blob/main/docs/linux.md#uninstall"
fi

[ "$STEPS" = 0 ] && exit 0
if [ "$DRY_RUN" = 1 ]; then
    _info "Dry run: nothing was removed."
    exit 0
fi
if [ "$YES" = 0 ]; then
    if [ ! -t 0 ]; then
        _err "Not a terminal; pass --yes to confirm."
        exit 1
    fi
    printf 'Proceed? [y/N] '
    read -r _answer || _answer=""
    case "$_answer" in
        y|Y|yes) ;;
        *) _info "Cancelled; nothing was removed."; exit 0 ;;
    esac
fi

MODE=run
_steps
_info "Done. Reinstall with: make install-dev   (or make install)"
