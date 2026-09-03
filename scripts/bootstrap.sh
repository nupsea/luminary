#!/usr/bin/env bash
# bootstrap.sh — one-command Luminary install for Apple Silicon Macs.
#
#   curl -fsSL https://raw.githubusercontent.com/nupsea/luminary/master/scripts/bootstrap.sh | bash
#
# Installs into ~/.luminary, registers a login-time service, downloads ~5GB of
# models, and opens the app. Non-interactive and safe to re-run (re-running
# upgrades the app and preserves the library).
#
# Requires no Homebrew, no Node, no git, and no compiler.

set -euo pipefail

# The application and the library are deliberately separate trees. ~/.luminary is
# the long-standing library location (documented in docs/architecture.md), so an
# existing install is adopted in place rather than orphaned; the app prefix is
# replaced wholesale on upgrade and must never contain user data.
PREFIX="${LUMINARY_PREFIX:-$HOME/Library/Application Support/Luminary}"
DATA_DIR="${LUMINARY_DATA_DIR:-$HOME/.luminary}"
PORT="${LUMINARY_PORT:-7820}"
REPO="${LUMINARY_REPO:-nupsea/luminary}"
VERSION="${LUMINARY_VERSION:-latest}"
# Empty by default: resolved from the sized profile in step 5, never a fixed
# name. This wrote LITELLM_DEFAULT_MODEL=ollama/llama3.2 into the user's .env,
# which is a hard pin that outlives every host-aware default the app has.
CHAT_MODEL="${LUMINARY_CHAT_MODEL:-}"
VISION_MODEL="${LUMINARY_VISION_MODEL:-}"
PROFILE="${LUMINARY_PROFILE:-}"
BOOT_TIMEOUT="${LUMINARY_BOOT_TIMEOUT:-300}"

APP_DIR="$PREFIX/app"
RUNTIME_DIR="$PREFIX/runtime"
LOG_DIR="$PREFIX/logs"
BIN_DIR="${LUMINARY_BIN_DIR:-$HOME/.local/bin}"
VENV_DIR="$RUNTIME_DIR/venv"
UV="$RUNTIME_DIR/bin/uv"
PLIST="$HOME/Library/LaunchAgents/sh.luminary.app.plist"
LABEL="sh.luminary.app"

STEP=0
_step()  { STEP=$((STEP + 1)); printf '\n\033[0;36m[%d/10]\033[0m \033[1m%s\033[0m\n' "$STEP" "$*"; }
_info()  { printf '       %s\n' "$*"; }
_warn()  { printf '\033[0;33m  warn\033[0m %s\n' "$*"; }
_die()   {
    local duration=$(( $(date +%s) - INSTALL_START_TIME ))
    _send_telemetry "install.macos_bootstrap.failed" "failed" "$duration"
    printf '\n\033[0;31m  error\033[0m %s\n\n' "$*" >&2
    exit 1
}
_have()  { command -v "$1" >/dev/null 2>&1; }
_quote() { sed 's/^/       | /'; }

INSTALL_START_TIME="$(date +%s)"
TELEMETRY_APP_ID="${LUMINARY_TELEMETRY_APP_ID:-}"

_lower() { printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]'; }

_opted_out() {
    case "$(_lower "${DO_NOT_TRACK:-}")" in 1|true|yes) return 0 ;; esac
    case "$(_lower "${LUMINARY_TELEMETRY_DISABLED:-}")" in 1|true|yes) return 0 ;; esac
    case "$(_lower "${LUMINARY_TELEMETRY:-}")" in 0|false|no) return 0 ;; esac
    return 1
}

_send_telemetry() {
    local signal_type="$1"
    local status="${2:-unknown}"
    local duration="${3:-0}"

    # Values match `anonymous_telemetry.is_telemetry_opted_out`: the backend
    # accepts 1/true/yes, and accepting only "1" here meant DO_NOT_TRACK=true
    # opted a user out of the app while the installer still reported.
    if _opted_out; then
        return 0
    fi
    _have curl || return 0

    local telemetry_id_file="$DATA_DIR/.telemetry_id"
    local client_id=""
    if [ -f "$telemetry_id_file" ]; then
        client_id="$(cat "$telemetry_id_file" 2>/dev/null || true)"
    fi
    if [ -z "$client_id" ]; then
        if _have uuidgen; then
            client_id="$(uuidgen 2>/dev/null || true)"
        fi
        [ -n "$client_id" ] || client_id="$(date +%s)-$$-$RANDOM"
    fi

    local arch="$(uname -m)"
    local payload="{\"os\":\"macOS\",\"arch\":\"$arch\",\"status\":\"$status\",\"duration_seconds\":$duration,\"install_source\":\"macos_bootstrap\",\"version\":\"$VERSION\"}"

    # Forward to TelemetryDeck if configured
    if [ -n "$TELEMETRY_APP_ID" ]; then
        (curl -s -m 3 -X POST "https://nom.telemetrydeck.com/v2/" \
            -H "Content-Type: application/json; charset=utf-8" \
            -d "[{\"appID\":\"$TELEMETRY_APP_ID\",\"clientUser\":\"$client_id\",\"type\":\"$signal_type\",\"payload\":$payload}]" >/dev/null 2>&1 &) || true
    fi

    # Both paths: the prefix depends on the backend's mode. `_API_PREFIX` is
    # "/api" only under LUMINARY_MODE=public (Docker); a normal install runs
    # `full`, where the route is unprefixed. The /api path alone 404s there,
    # silently, because this call discards its output.
    local body="{\"signal_type\":\"$signal_type\",\"payload\":$payload}"
    for _path in "/monitoring/telemetry/event" "/api/monitoring/telemetry/event"; do
        (curl -s -m 1 -X POST "http://127.0.0.1:$PORT${_path}" \
            -H "Content-Type: application/json" \
            -d "$body" >/dev/null 2>&1 &) || true
    done
}

_send_telemetry "install.macos_bootstrap.started" "started" 0

# Run a command with a wall-clock bound. macOS ships no `timeout`, and an
# unbounded diagnostic that hangs is worse than the failure it is diagnosing.
# Returns 124 when the bound is hit, otherwise the command's own status.
_bounded() {
    local secs="$1"; shift
    "$@" & local pid=$! waited=0
    while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt "$secs" ]; do
        sleep 1; waited=$((waited + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        return 124
    fi
    wait "$pid"
}

# "Logs: <path>" is useless advice when the failure is that the file was never
# created -- which is what happens when the process dies during import, before
# uvicorn writes its first line. So import the backend here instead, where the
# traceback has somewhere to go.
_boot_report() {
    _info "launchd:"
    if launchctl print "gui/$(id -u)/$LABEL" >"$TMPDIR_BOOT/lc.txt" 2>/dev/null; then
        # grep -E, not sed: BSD sed has no \| alternation, so the pattern this
        # replaces matched nothing and printed an empty launchd section.
        grep -E '^[[:space:]]*(state|pid|last exit code|last exit status) =' \
            "$TMPDIR_BOOT/lc.txt" | sed 's/^[[:space:]]*//' | _quote \
            || printf '       | registered, but reported no state\n'
    else
        printf '       | service is not registered\n'
    fi

    if [ -s "$LOG_DIR/luminary.log" ]; then
        _info "last 20 lines of $LOG_DIR/luminary.log:"
        tail -n 20 "$LOG_DIR/luminary.log" | _quote
        return
    fi

    _info "No log was written, so the server never reached startup."
    _info "Importing the backend directly to surface the error:"
    # Same working directory as the service: config.py reads a CWD-relative
    # .env, so importing from anywhere else would exercise a different config.
    if _bounded 180 bash -c \
        'cd "$1" && PYTHONPATH="$1" DATA_DIR="$2" "$3" -c "import app.main"' \
        _ "$APP_DIR/backend" "$DATA_DIR" "$VENV_DIR/bin/python" \
        >"$TMPDIR_BOOT/import.txt" 2>&1; then
        _info "The backend imports cleanly, so this is a slow start, not a crash."
        _info "Re-run with LUMINARY_BOOT_TIMEOUT=600, or run: $BIN_DIR/luminary start"
    else
        [ -s "$TMPDIR_BOOT/import.txt" ] \
            && tail -n 30 "$TMPDIR_BOOT/import.txt" | _quote \
            || printf '       | the import produced no output and did not finish\n'
    fi
}

TMPDIR_BOOT="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_BOOT"' EXIT

cat <<'BANNER'

  Luminary — local-first learning assistant

  This installs into ~/.luminary and downloads about 5GB of models.
  Expect 15-25 minutes on a first install.

  Your documents, notes and questions never leave this machine. The installer
  reports an anonymous platform and success/failure signal so we know which
  systems to support. Set DO_NOT_TRACK=1 to send nothing at all.

BANNER

# ---------------------------------------------------------------------------
# 1. Preflight
# ---------------------------------------------------------------------------
_step "Checking this Mac"

[ "$(uname -s)" = "Darwin" ] || _die "This installer is macOS-only."

if [ "$(uname -m)" != "arm64" ]; then
    _die "Apple Silicon required — lancedb publishes no macOS x86_64 wheel.
       On an Intel Mac, run Luminary via Docker instead:
         docker compose --profile ai up"
fi

MACOS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
if [ "$MACOS_MAJOR" -lt 14 ]; then
    _die "macOS 14 (Sonoma) or newer required — you have $(sw_vers -productVersion).
       Both onnxruntime and Ollama require it."
fi

_info "macOS $(sw_vers -productVersion) on Apple Silicon — supported."

mkdir -p "$PREFIX" "$DATA_DIR" "$RUNTIME_DIR/bin" "$LOG_DIR" "$BIN_DIR"

# An existing library must be adopted, never shadowed by an empty one.
if [ -f "$DATA_DIR/luminary.db" ]; then
    _info "Found an existing library at $DATA_DIR — it will be used as-is."
fi

# ---------------------------------------------------------------------------
# 2. Resolve + download the release
# ---------------------------------------------------------------------------
_step "Fetching Luminary"

if [ "$VERSION" = "latest" ]; then
    _info "Resolving latest release..."
    VERSION="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
        | sed -n 's/.*"tag_name" *: *"v\{0,1\}\([^"]*\)".*/\1/p' | head -1)"
    [ -n "$VERSION" ] || _die "Could not resolve the latest release of $REPO."
fi

TARBALL="luminary-$VERSION-macos.tar.gz"
BASE_URL="https://github.com/$REPO/releases/download/v$VERSION"

_info "Version $VERSION"
curl -fSL --progress-bar -o "$TMPDIR_BOOT/$TARBALL" "$BASE_URL/$TARBALL" \
    || _die "Download failed: $BASE_URL/$TARBALL"

if curl -fsSL -o "$TMPDIR_BOOT/$TARBALL.sha256" "$BASE_URL/$TARBALL.sha256" 2>/dev/null; then
    (cd "$TMPDIR_BOOT" && shasum -a 256 -c "$TARBALL.sha256" >/dev/null) \
        || _die "Checksum mismatch — refusing to install a corrupted or tampered download."
    _info "Checksum verified."
else
    _warn "No checksum published for this release; skipping verification."
fi

# Extract to a staging dir and swap, so a failed download never leaves a
# half-replaced app directory behind.
tar -xzf "$TMPDIR_BOOT/$TARBALL" -C "$TMPDIR_BOOT"
STAGED="$TMPDIR_BOOT/luminary-$VERSION"
[ -f "$STAGED/backend/app/main.py" ] || _die "Release payload looks malformed."

# The app directory is replaced wholesale. DATA_DIR lives outside it on purpose.
rm -rf "$APP_DIR"
mkdir -p "$(dirname "$APP_DIR")"
mv "$STAGED" "$APP_DIR"
_info "Installed to $APP_DIR"

# ---------------------------------------------------------------------------
# 3. Python runtime
# ---------------------------------------------------------------------------
_step "Setting up the Python runtime"

if [ ! -x "$UV" ]; then
    _info "Installing uv..."
    # UV_UNMANAGED_INSTALL pins the binary to our prefix, skips shell-profile
    # edits, and disables self-update — an installer must not touch ~/.zshrc.
    curl -LsSf https://astral.sh/uv/install.sh \
        | env UV_UNMANAGED_INSTALL="$RUNTIME_DIR/bin" sh >/dev/null 2>&1 \
        || _die "Failed to install uv."
    [ -x "$UV" ] || _die "uv installed but not found at $UV"
fi
_info "uv $("$UV" --version 2>/dev/null | awk '{print $2}')"

_info "Installing dependencies (this pulls Python 3.13 and ~1.6GB of packages)..."
# Both flags are load-bearing. --no-default-groups drops dev/media (Phoenix,
# pytest, whisper); --group full adds back yt-dlp and the tree-sitter grammars,
# without which YouTube and code ingestion refuse everything offered to them.
# Keep in step with scripts/macos/stage_python.sh, which builds the same profile.
(
    cd "$APP_DIR/backend"
    UV_PROJECT_ENVIRONMENT="$VENV_DIR" "$UV" sync --no-default-groups --group full --quiet
) || _die "Dependency install failed. See above."
_info "Runtime ready at $VENV_DIR"

# ---------------------------------------------------------------------------
# 4. Ollama
# ---------------------------------------------------------------------------
_step "Setting up Ollama"

OLLAMA_BIN=""
if _have ollama; then
    OLLAMA_BIN="$(command -v ollama)"
    _info "Using existing Ollama at $OLLAMA_BIN"
elif [ -x "/Applications/Ollama.app/Contents/Resources/ollama" ]; then
    OLLAMA_BIN="/Applications/Ollama.app/Contents/Resources/ollama"
    _info "Found Ollama.app already installed."
else
    _info "Downloading Ollama..."
    curl -fSL --progress-bar -o "$TMPDIR_BOOT/Ollama.dmg" "https://ollama.com/download/Ollama.dmg" \
        || _die "Could not download Ollama. Install it from https://ollama.com and re-run."

    MOUNT="$TMPDIR_BOOT/ollama-mnt"
    mkdir -p "$MOUNT"
    hdiutil attach -quiet -nobrowse -mountpoint "$MOUNT" "$TMPDIR_BOOT/Ollama.dmg" \
        || _die "Could not mount the Ollama disk image."

    if cp -R "$MOUNT/Ollama.app" /Applications/ 2>/dev/null; then
        _info "Installed Ollama.app to /Applications."
    else
        hdiutil detach -quiet "$MOUNT" || true
        _die "Could not write to /Applications. Install Ollama manually from
       https://ollama.com and re-run this script."
    fi
    hdiutil detach -quiet "$MOUNT" || true
    OLLAMA_BIN="/Applications/Ollama.app/Contents/Resources/ollama"
fi

[ -x "$OLLAMA_BIN" ] || _die "Ollama CLI not found at $OLLAMA_BIN"
ln -sf "$OLLAMA_BIN" "$RUNTIME_DIR/bin/ollama"
OLLAMA_BIN_DIR="$(dirname "$OLLAMA_BIN")"

# ---------------------------------------------------------------------------
# 5. Performance profile
# ---------------------------------------------------------------------------
_step "Sizing for this machine"

# Sized on memory: each slot costs a full KV cache. The bands and the models
# they select are the same three as install.sh, and test_installer_models.py
# fails when either drifts from the registry.
#   under 16GB  one model resident, so it must be one that also reads figures
#   16-24GB     two slots, generalist for both roles
#   over 24GB   two slots, and at 26GB+ the large text model with the
#               generalist kept for figures -- see LARGE_TEXT_MIN_RAM_GB below
PUBLIC_GENERALIST="qwen3.5:4b"
LARGE_TEXT_MODEL="qwen2.5:14b-instruct"
DEFAULT_CHAT_MODEL="qwen3.5:4b"
# Mirrors LARGE_TEXT_MIN_RAM_GB in install.sh, for the same measured reason: the
# large text model plus the generalist is 12.88GB against a half-of-RAM budget,
# so the pair needs 25.76GB. Without this gate `LUMINARY_PROFILE=performance` on
# a small Mac pulled 9.67GB the backend then refuses to load.
LARGE_TEXT_MIN_RAM_GB=26

MEM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
# `low` is the backend's canonical name for the small profile; `public` is this
# script's. Accept both, then validate -- an unrecognised value used to fall into
# the `*)` arm, take standard knobs, and be written to .env verbatim, where the
# backend rejects it and re-sizes. Installer and app disagreeing, silently.
[ "$PROFILE" = "low" ] && PROFILE="public"
case "${PROFILE:-public}" in
    public|standard|performance) ;;
    *)
        _die "LUMINARY_PROFILE='$PROFILE' is not one of: low, public, standard, performance."
        ;;
esac
if [ -z "$PROFILE" ]; then
    if   [ "$MEM_GB" -lt 16 ]; then PROFILE="public"
    elif [ "$MEM_GB" -le 24 ]; then PROFILE="standard"
    else                            PROFILE="performance"
    fi
fi
case "$PROFILE" in
    public)
        MAX_LOADED=1; NUM_PARALLEL=1; VISION_CONCURRENCY=1
        [ -z "$CHAT_MODEL" ] && CHAT_MODEL="$PUBLIC_GENERALIST"
        ;;
    performance)
        MAX_LOADED=2; NUM_PARALLEL=4; VISION_CONCURRENCY=4
        if [ -z "$CHAT_MODEL" ]; then
            if [ "$MEM_GB" -ge "$LARGE_TEXT_MIN_RAM_GB" ]; then
                CHAT_MODEL="$LARGE_TEXT_MODEL"
            else
                CHAT_MODEL="$DEFAULT_CHAT_MODEL"
            fi
        fi
        [ -z "$VISION_MODEL" ] && [ "$CHAT_MODEL" != "$PUBLIC_GENERALIST" ] \
            && VISION_MODEL="$PUBLIC_GENERALIST"
        ;;
    *)
        MAX_LOADED=2; NUM_PARALLEL=2; VISION_CONCURRENCY=2
        [ -z "$CHAT_MODEL" ] && CHAT_MODEL="$DEFAULT_CHAT_MODEL"
        ;;
esac
_info "${MEM_GB}GB RAM -> '$PROFILE' profile, $CHAT_MODEL${VISION_MODEL:+ + $VISION_MODEL}"

# The backend calls the small profile `low`; `public` is its name here and on
# the install.sh side, and collides with LUMINARY_MODE=public. Write the
# canonical name so a fresh install does not depend on a legacy alias.
case "$PROFILE" in
    public) BACKEND_PROFILE="low" ;;
    *)      BACKEND_PROFILE="$PROFILE" ;;
esac

# Ollama.app is launched by launchd and does not inherit this shell's env, so
# the knobs go into the GUI session before it starts. Set BEFORE launching.
launchctl setenv OLLAMA_MAX_LOADED_MODELS "$MAX_LOADED" 2>/dev/null || true
launchctl setenv OLLAMA_NUM_PARALLEL "$NUM_PARALLEL" 2>/dev/null || true

if curl -sf --max-time 2 "http://127.0.0.1:11434/api/version" >/dev/null 2>&1; then
    _info "Ollama already running (profile applies after its next restart)."
else
    _info "Starting Ollama..."
    open -a Ollama 2>/dev/null || nohup "$OLLAMA_BIN" serve >"$LOG_DIR/ollama.log" 2>&1 &
    for i in $(seq 1 30); do
        sleep 1
        curl -sf --max-time 2 "http://127.0.0.1:11434/api/version" >/dev/null 2>&1 && break
        [ "$i" -eq 30 ] && _die "Ollama did not start. Open the Ollama app manually and re-run."
    done
    _info "Ollama is up."
fi

# ---------------------------------------------------------------------------
# 6. Configuration
# ---------------------------------------------------------------------------
_step "Writing configuration"

ENV_FILE="$APP_DIR/backend/.env"
if [ -f "$APP_DIR/backend/.env.example" ]; then
    SRC="$APP_DIR/backend/.env.example"
else
    SRC=""
fi

if [ -n "$SRC" ]; then
    sed -e "s|@@DATA_DIR@@|$DATA_DIR|g" \
        -e "s|@@LUMINARY_MODE@@|public|g" \
        -e "s|@@VISION_CONCURRENCY@@|$VISION_CONCURRENCY|g" \
        -e "s|@@OLLAMA_NUM_PARALLEL@@|$NUM_PARALLEL|g" \
        "$SRC" > "$ENV_FILE"
    # Appended rather than templated because this installer *pulled* specific
    # models: leaving them unset lets the app resolve one that is not on disk,
    # which fails at the first question instead of at install time. The template
    # sets these keys itself, so strip them first -- appending alone left the
    # file carrying each key twice with different values, and a user editing the
    # first occurrence saw no effect.
    grep -vE '^(LITELLM_DEFAULT_MODEL|VISION_MODEL|LUMINARY_MEMORY_PROFILE)=' \
        "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
    cat >> "$ENV_FILE" <<EOF

# Written by bootstrap.sh from the sized profile. Edit freely -- these are
# ordinary settings, and the app follows whatever is here.
LITELLM_DEFAULT_MODEL=ollama/$CHAT_MODEL
VISION_MODEL=ollama/${VISION_MODEL:-$CHAT_MODEL}
LUMINARY_MEMORY_PROFILE=$BACKEND_PROFILE
EOF
else
    cat > "$ENV_FILE" <<EOF
DATA_DIR=$DATA_DIR
LUMINARY_MODE=public
LOG_LEVEL=INFO
OLLAMA_URL=http://127.0.0.1:11434
LITELLM_DEFAULT_MODEL=ollama/$CHAT_MODEL
VISION_MODEL=ollama/${VISION_MODEL:-$CHAT_MODEL}
LUMINARY_MEMORY_PROFILE=$BACKEND_PROFILE
ENRICHMENT_VISION_CONCURRENCY=$VISION_CONCURRENCY
OLLAMA_NUM_PARALLEL=$NUM_PARALLEL
GLINER_ENABLED=true
PHOENIX_ENABLED=false
EOF
fi
_info "Wrote $ENV_FILE"

# ---------------------------------------------------------------------------
# 7. Chat model
# ---------------------------------------------------------------------------
_step "Downloading the language model${VISION_MODEL:+s}"

for model in "$CHAT_MODEL" "$VISION_MODEL"; do
    [ -z "$model" ] && continue
    if "$OLLAMA_BIN" list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$model\(:latest\)\?"; then
        _info "$model already present."
    else
        "$OLLAMA_BIN" pull "$model" || _die "Failed to pull $model."
    fi
done

# ---------------------------------------------------------------------------
# 8. Warm the ML models
# ---------------------------------------------------------------------------
_step "Downloading embedding, entity and reranking models (~1.4GB)"

_info "These normally download silently on first use — doing it now so the app"
_info "is genuinely ready when it opens."

(
    cd "$APP_DIR/backend"
    DATA_DIR="$DATA_DIR" LUMINARY_MODE=public PYTHONPATH="$APP_DIR/backend" \
    "$VENV_DIR/bin/python" - <<'PY'
import sys

# Same loaders the app's lifespan warmup uses, run in the foreground so the
# download is visible and finished before the service is declared ready.
stages = [
    ("embedding model", "app.services.embedder", lambda m: m.get_embedding_service()._load_model()),
    ("entity model", "app.services.ner", lambda m: m.get_entity_extractor()._load_model()),
    ("reranker", "app.services.retriever_strategies", lambda m: m._get_reranker()._load()),
]

failed = []
for label, module, load in stages:
    try:
        print(f"       downloading {label}...", flush=True)
        load(__import__(module, fromlist=["_"]))
        print(f"       {label} ready", flush=True)
    except Exception as exc:
        print(f"       WARN {label} failed: {exc}", flush=True)
        failed.append(label)

# Non-fatal: these retry lazily at first use. Surface it, don't block install.
sys.exit(0)
PY
) || _warn "Some models could not be pre-downloaded; they will retry on first use."

# ---------------------------------------------------------------------------
# 9. Background service
# ---------------------------------------------------------------------------
_step "Registering the background service"

mkdir -p "$HOME/Library/LaunchAgents"

TEMPLATE="$APP_DIR/scripts/launchd/sh.luminary.app.plist.template"
if [ -f "$TEMPLATE" ]; then
    sed -e "s|@@PREFIX@@|$PREFIX|g" \
        -e "s|@@PORT@@|$PORT|g" \
        -e "s|@@DATA_DIR@@|$DATA_DIR|g" \
        -e "s|@@OLLAMA_BIN_DIR@@|$OLLAMA_BIN_DIR|g" \
        "$TEMPLATE" > "$PLIST"
else
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key><string>$LABEL</string>
	<key>ProgramArguments</key>
	<array>
		<string>$VENV_DIR/bin/python</string><string>-m</string><string>uvicorn</string>
		<string>app.main:app</string>
		<string>--host</string><string>127.0.0.1</string>
		<string>--port</string><string>$PORT</string>
	</array>
	<key>WorkingDirectory</key><string>$APP_DIR/backend</string>
	<key>EnvironmentVariables</key>
	<dict>
		<key>DATA_DIR</key><string>$DATA_DIR</string>
		<key>LUMINARY_MODE</key><string>public</string>
		<key>PYTHONPATH</key><string>$APP_DIR/backend</string>
		<key>PYTHONUNBUFFERED</key><string>1</string>
		<key>PATH</key><string>$VENV_DIR/bin:$OLLAMA_BIN_DIR:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
	</dict>
	<key>RunAtLoad</key><true/>
	<key>KeepAlive</key><true/>
	<key>ThrottleInterval</key><integer>10</integer>
	<key>ProcessType</key><string>Interactive</string>
	<key>StandardOutPath</key><string>$LOG_DIR/luminary.log</string>
	<key>StandardErrorPath</key><string>$LOG_DIR/luminary.log</string>
</dict>
</plist>
EOF
fi

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null \
    || launchctl load -w "$PLIST" 2>/dev/null \
    || _die "Could not register the background service."
_info "Service registered — Luminary will start automatically at login."

# Install the CLI if the payload ships one.
if [ -f "$APP_DIR/scripts/cli/luminary" ]; then
    install -m 0755 "$APP_DIR/scripts/cli/luminary" "$BIN_DIR/luminary"
    _info "CLI installed at $BIN_DIR/luminary"
fi

# ---------------------------------------------------------------------------
# 10. Wait for ready, then open
# ---------------------------------------------------------------------------
_step "Starting Luminary"

# uvicorn logs nothing until app.main finishes importing torch, lancedb and the
# NER model, so an empty log is expected for the first minutes, not a symptom.
# 90s was under that on a cold machine and failed installs that were starting.
_info "First start imports the model stack and can take a few minutes."

READY=0
DEADLINE=$(( $(date +%s) + BOOT_TIMEOUT ))
NEXT_TICK=$(( $(date +%s) + 30 ))
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    if curl -sf --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        READY=1; break
    fi
    if [ "$(date +%s)" -ge "$NEXT_TICK" ]; then
        _info "still starting... ($(( $(date +%s) - DEADLINE + BOOT_TIMEOUT ))s)"
        NEXT_TICK=$(( $(date +%s) + 30 ))
    fi
    sleep 2
done

if [ "$READY" -ne 1 ]; then
    printf '\n'
    _warn "Luminary did not answer on port $PORT within ${BOOT_TIMEOUT}s."
    _boot_report
    _die "Luminary did not come up. The report above says why.
       Raise the wait with LUMINARY_BOOT_TIMEOUT=600 and re-run if this
       machine is simply slow, or open an issue with the report attached:
       https://github.com/$REPO/issues"
fi

open "http://127.0.0.1:$PORT" 2>/dev/null || true

cat <<EOF

  Luminary $VERSION is running at http://localhost:$PORT

  It starts automatically at login. To manage it:

    "$BIN_DIR/luminary" status
    "$BIN_DIR/luminary" stop
    "$BIN_DIR/luminary" uninstall

EOF

if ! command -v luminary >/dev/null 2>&1; then
    cat <<EOF
  Add the command to your PATH:

    echo 'export PATH="\$HOME/.local/bin:\$PATH"' >> ~/.zshrc

EOF
fi

cat <<EOF
  Your library:     $DATA_DIR   (never touched by upgrades)
  The application:  $PREFIX

EOF

INSTALL_DURATION=$(( $(date +%s) - INSTALL_START_TIME ))
_send_telemetry "install.macos_bootstrap.completed" "success" "$INSTALL_DURATION"

