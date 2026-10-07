#!/usr/bin/env bash
# uninstall.sh — undo `make install` / `make install-dev` for this checkout.
#
# Removes what lives in the checkout (backend/.venv, frontend/node_modules,
# frontend/dist, the installer's keys in backend/.env) and whatever install.sh
# recorded in .install-manifest as installed by it. A tool that was already on
# the machine is never recorded, so it is never removed; unrecorded leftovers
# Luminary may have added are listed at the end for the user to check. The
# library (.luminary/) is kept unless --purge-data.
#
# Usage: bash scripts/uninstall.sh [--dry-run] [--yes] [--purge-data]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/.install-manifest"
TEST_MODELS="${LUMINARY_TEST_MODEL_CACHE:-$HOME/.cache/luminary/test-models}"
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
_size() { du -sh "$1" 2>/dev/null | awk '{print $1}'; }
_recorded() { [ -f "$MANIFEST" ] && grep -qxF "$1" "$MANIFEST"; }

# Deleting the venv under a running backend leaves it half-dead holding the DB.
# Minimal Linux images ship no lsof; bash's /dev/tcp connect needs nothing.
_listening() {
    if _have lsof; then
        lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN >/dev/null 2>&1
    else
        (exec 3<>"/dev/tcp/127.0.0.1/$BACKEND_PORT") 2>/dev/null
    fi
}
if _listening; then
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
    find "$REPO_ROOT" \( -name .git -o -name .venv -o -name node_modules -o -name .luminary \) -prune -o \
        \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -type d -print -prune
    if [ -f "$REPO_ROOT/backend/.coverage" ]; then echo "$REPO_ROOT/backend/.coverage"; fi
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
        _act "Remove Python caches and coverage data (__pycache__, .pytest_cache, .ruff_cache, .coverage)" _remove_python_caches
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
    if _recorded test-models && [ -d "$TEST_MODELS" ]; then
        _act "Remove the test suite's model cache $TEST_MODELS ($(_size "$TEST_MODELS"))" rm -rf "$TEST_MODELS"
    fi
    if _recorded uv && _have uv; then
        _act "Uninstall uv: binary, its cache ($(_size "$(uv cache dir)")) and its Pythons" _remove_uv
    fi
    _act "Forget the install record (.install-manifest)" rm -f "$MANIFEST"
}

# Models this checkout used, read before backend/.env is stripped, plus the
# installer's defaults: an install that predates the manifest pulled one of these.
_candidate_models() {
    sed -n -E 's/^(LITELLM_DEFAULT_MODEL|VISION_MODEL)=ollama\///p' "$REPO_ROOT/backend/.env" 2>/dev/null || true
    sed -n -E 's/^(DEFAULT_CHAT_MODEL|PUBLIC_GENERALIST|LARGE_TEXT_MODEL)="([^"]+)"/\2/p' \
        "$REPO_ROOT/scripts/install.sh" 2>/dev/null || true
}

_hand() { printf '  - %s\n      %s\n' "$1" "$2"; }

# Listed, never run: without a record these may be the user's own.
_by_hand() {
    local model pulled
    if _have ollama; then
        pulled="$(ollama list 2>/dev/null | awk 'NR>1 {print $1}')"
        for model in $(_candidate_models | sort -u); do
            _recorded "model:$model" && continue
            if printf '%s\n' "$pulled" | grep -qxF -e "$model" -e "$model:latest"; then
                _hand "Ollama model $model" "ollama rm $model"
            fi
        done
    fi
    if _have brew && ! _recorded node:brew && brew list --formula node >/dev/null 2>&1; then
        _hand "Node (brew), if nothing else of yours uses it" "brew uninstall node && brew autoremove"
    fi
    if _have brew && ! _recorded ollama:brew && brew list --formula ollama >/dev/null 2>&1; then
        _hand "Ollama (brew), if nothing else of yours uses it" "brew uninstall ollama"
    fi
    if ! _recorded node:local && [ -d "$HOME/.local/share/luminary/node" ]; then
        _hand "Node in ~/.local/share/luminary/node" "rm -rf ~/.local/share/luminary/node"
    fi
    if ! _recorded test-models && [ -d "$TEST_MODELS" ]; then
        _hand "Test suite model cache ($(_size "$TEST_MODELS")), shared by every checkout" "rm -rf $TEST_MODELS"
    fi
    # Full path: this script adds ~/.local/bin to PATH; the user's shell may not.
    if ! _recorded uv && _have uv; then
        local uv_bin
        uv_bin="$(command -v uv)"
        _hand "uv's download cache ($(_size "$(uv cache dir)"))" "$uv_bin cache clean"
        _hand "Pythons uv manages ($(_size "$(uv python dir)")), if no other project uses them" "$uv_bin python uninstall --all"
    fi
}

_print_by_hand() {
    [ -n "$BY_HAND" ] || return 0
    printf '\nNot removed: no install record says this checkout added these. Check each,\nand remove it by hand if Luminary installed it:\n%s\n' "$BY_HAND"
}

BY_HAND="$(_by_hand)"
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
if _recorded ollama:script; then
    _warn "Ollama was installed by its Linux script; removing it needs root: https://github.com/ollama/ollama/blob/main/docs/linux.md#uninstall"
fi

if [ "$STEPS" = 0 ]; then _print_by_hand; exit 0; fi
if [ "$DRY_RUN" = 1 ]; then
    _info "Dry run: nothing was removed."
    _print_by_hand
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
_print_by_hand
