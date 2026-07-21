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

PREFIX="${LUMINARY_PREFIX:-$HOME/.luminary}"
PORT="${LUMINARY_PORT:-7820}"
REPO="${LUMINARY_REPO:-nupsea/luminary}"
VERSION="${LUMINARY_VERSION:-latest}"
CHAT_MODEL="${LUMINARY_CHAT_MODEL:-llama3.2}"
PROFILE="${LUMINARY_PROFILE:-}"

APP_DIR="$PREFIX/app"
DATA_DIR="$PREFIX/data"
RUNTIME_DIR="$PREFIX/runtime"
LOG_DIR="$PREFIX/logs"
BIN_DIR="$PREFIX/bin"
VENV_DIR="$RUNTIME_DIR/venv"
UV="$RUNTIME_DIR/bin/uv"
PLIST="$HOME/Library/LaunchAgents/sh.luminary.app.plist"
LABEL="sh.luminary.app"

STEP=0
_step()  { STEP=$((STEP + 1)); printf '\n\033[0;36m[%d/10]\033[0m \033[1m%s\033[0m\n' "$STEP" "$*"; }
_info()  { printf '       %s\n' "$*"; }
_warn()  { printf '\033[0;33m  warn\033[0m %s\n' "$*"; }
_die()   { printf '\n\033[0;31m  error\033[0m %s\n\n' "$*" >&2; exit 1; }
_have()  { command -v "$1" >/dev/null 2>&1; }

TMPDIR_BOOT="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_BOOT"' EXIT

cat <<'BANNER'

  Luminary — local-first learning assistant

  This installs into ~/.luminary and downloads about 5GB of models.
  Expect 15-25 minutes on a first install. Nothing is sent anywhere.

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
# --no-default-groups is load-bearing: pyproject sets default-groups=[dev,full],
# which would drag in Phoenix, pytest, whisper and roughly double the install.
(
    cd "$APP_DIR/backend"
    UV_PROJECT_ENVIRONMENT="$VENV_DIR" "$UV" sync --no-default-groups --quiet
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

MEM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
if [ -z "$PROFILE" ]; then
    if   [ "$MEM_GB" -lt 12 ]; then PROFILE="public"
    elif [ "$MEM_GB" -lt 24 ]; then PROFILE="standard"
    else                            PROFILE="performance"
    fi
fi
case "$PROFILE" in
    public)      MAX_LOADED=1; NUM_PARALLEL=1; VISION_CONCURRENCY=1 ;;
    performance) MAX_LOADED=2; NUM_PARALLEL=4; VISION_CONCURRENCY=4 ;;
    *)           MAX_LOADED=2; NUM_PARALLEL=2; VISION_CONCURRENCY=2 ;;
esac
_info "${MEM_GB}GB RAM -> '$PROFILE' profile"

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
        "$SRC" > "$ENV_FILE"
else
    cat > "$ENV_FILE" <<EOF
DATA_DIR=$DATA_DIR
LUMINARY_MODE=public
LOG_LEVEL=INFO
OLLAMA_URL=http://127.0.0.1:11434
LITELLM_DEFAULT_MODEL=ollama/$CHAT_MODEL
ENRICHMENT_VISION_CONCURRENCY=$VISION_CONCURRENCY
GLINER_ENABLED=true
PHOENIX_ENABLED=false
EOF
fi
_info "Wrote $ENV_FILE"

# ---------------------------------------------------------------------------
# 7. Chat model
# ---------------------------------------------------------------------------
_step "Downloading the language model (~2GB)"

if "$OLLAMA_BIN" list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$CHAT_MODEL\(:latest\)\?"; then
    _info "$CHAT_MODEL already present."
else
    "$OLLAMA_BIN" pull "$CHAT_MODEL" || _die "Failed to pull $CHAT_MODEL."
fi

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

READY=0
for i in $(seq 1 90); do
    if curl -sf --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        READY=1; break
    fi
    sleep 1
done

if [ "$READY" -ne 1 ]; then
    _die "Luminary did not come up on port $PORT.
       Logs: $LOG_DIR/luminary.log"
fi

open "http://127.0.0.1:$PORT" 2>/dev/null || true

cat <<EOF

  Luminary $VERSION is running at http://localhost:$PORT

  It starts automatically at login. To manage it:

    $BIN_DIR/luminary status
    $BIN_DIR/luminary stop
    $BIN_DIR/luminary uninstall

  Add it to your PATH for convenience:

    echo 'export PATH="$BIN_DIR:\$PATH"' >> ~/.zshrc

  Your library lives in $DATA_DIR and is never touched by upgrades.

EOF
