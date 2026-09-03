# install.ps1 — Automated native Windows installer for Luminary.
#
# Installs everything per-user — no Administrator rights required. Safe to re-run.
# Handles dependencies and corporate proxies gracefully.
#
# Usage (normal PowerShell window, no elevation needed):
#   Set-ExecutionPolicy Bypass -Scope Process -Force; .\scripts\install.ps1

$ErrorActionPreference = "Stop"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "   Starting Luminary Windows Installer" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 0. Corporate Proxy / TLS settings (this session only)
# ---------------------------------------------------------------------------
# UV_SYSTEM_CERTS makes uv trust the OS certificate store, which on a managed
# machine already includes the corporate proxy's root CA -- this is the safe,
# verification-preserving path and is preferred. UV_INSECURE_HOST and npm's
# strict-ssl=false actually DISABLE certificate verification, so they are opt-in
# and, when enabled, are applied only to this PowerShell process (env vars), never
# written to the user's global npm config where they would silently weaken TLS for
# every future install.
$env:UV_SYSTEM_CERTS = "true"

if ($env:LUMINARY_INSECURE_TLS -eq "1") {
    Write-Warning "LUMINARY_INSECURE_TLS=1 set: DISABLING TLS certificate verification for uv and npm for THIS session only. Prefer importing your corporate root CA instead. Do not use on an untrusted network."
    $env:UV_INSECURE_HOST = "pypi.org files.pythonhosted.org pythonhosted.org"
    $env:NPM_CONFIG_STRICT_SSL = "false"
} else {
    Write-Host "[install] Using system certificate store (UV_SYSTEM_CERTS). If installs fail behind a TLS-inspecting proxy, re-run with `$env:LUMINARY_INSECURE_TLS='1' (relaxes verification for this session only)." -ForegroundColor Gray
}

# Helper to check if a command exists
function Test-CommandExists($Command) {
    return (Get-Command $Command -ErrorAction SilentlyContinue) -ne $null
}

# Persist a directory onto the *user* PATH (no admin needed) and the live session.
function Add-UserPath($Dir) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    if (($userPath -split ';') -notcontains $Dir) {
        $newPath = if ($userPath) { "$Dir;$userPath" } else { $Dir }
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    }
    if (($env:PATH -split ';') -notcontains $Dir) {
        $env:PATH = "$Dir;$env:PATH"
    }
}

# ---------------------------------------------------------------------------
# 2. Install Python 3.13 (if missing)
# ---------------------------------------------------------------------------
if (Test-CommandExists "python") {
    $pyVersion = python --version 2>&1
    Write-Host "[install] Python is already installed: $pyVersion" -ForegroundColor Green
} else {
    Write-Host "[install] Python not found. Installing Python 3.13 (per-user, no admin)..." -ForegroundColor Yellow
    # Pinned release — bump periodically as new 3.13.x patch releases land.
    $pyUrl = "https://www.python.org/ftp/python/3.13.0/python-3.13.0-amd64.exe"
    $pyPath = "$env:TEMP\python-3.13.0.exe"

    Write-Host "[install] Downloading Python installer..." -ForegroundColor Gray
    Invoke-WebRequest -Uri $pyUrl -OutFile $pyPath -UseBasicParsing

    Write-Host "[install] Running installer (this may take a minute)..." -ForegroundColor Gray
    Start-Process -FilePath $pyPath -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1" -Wait

    # Per-user install location; PrependPath=1 persists it to the user PATH.
    $pyBase = "$env:LOCALAPPDATA\Programs\Python\Python313"
    $env:PATH = "$pyBase\;$pyBase\Scripts\;$env:PATH"
    
    if (Test-CommandExists "python") {
        Write-Host "[install] Python installed successfully!" -ForegroundColor Green
    } else {
        Write-Warning "Python was installed, but is not yet on the PATH. You may need to restart PowerShell after installation."
    }
}

# ---------------------------------------------------------------------------
# 3. Install Node.js (if missing or version < 20)
# ---------------------------------------------------------------------------
$installNode = $true
if (Test-CommandExists "node") {
    $nodeVersion = node --version
    # Parse version string (e.g. "v14.15.1" -> "14")
    $cleanVersion = $nodeVersion.TrimStart('v')
    $majorVersionStr = $cleanVersion.Split('.')[0]
    $majorVersion = 0
    if ([int]::TryParse($majorVersionStr, [ref]$majorVersion)) {
        if ($majorVersion -ge 20) {
            Write-Host "[install] Node.js is already installed: $nodeVersion" -ForegroundColor Green
            $installNode = $false
        } else {
            Write-Host "[install] Node.js version $nodeVersion is too old. Luminary requires Node.js >= 20." -ForegroundColor Yellow
        }
    }
}

if ($installNode) {
    # Check if a Node version manager is available
    if (Test-CommandExists "fnm") {
        Write-Host "[install] Detected fnm. Using fnm to install/use Node 20..." -ForegroundColor Yellow
        try {
            Start-Process -FilePath "fnm" -ArgumentList "install", "20" -Wait -NoNewWindow
            Start-Process -FilePath "fnm" -ArgumentList "use", "20" -Wait -NoNewWindow
            # Apply fnm to the current PowerShell session environment
            $fnmEnv = fnm env --use-on-cd | Out-String
            Invoke-Expression $fnmEnv
            if (Test-CommandExists "node") {
                $nodeVersion = node --version
                $cleanVersion = $nodeVersion.TrimStart('v')
                $majorVersionStr = $cleanVersion.Split('.')[0]
                $majorVersion = 0
                if ([int]::TryParse($majorVersionStr, [ref]$majorVersion) -and $majorVersion -ge 20) {
                    Write-Host "[install] Node.js updated successfully via fnm: $nodeVersion" -ForegroundColor Green
                    $installNode = $false
                }
            }
        } catch {
            Write-Warning "fnm failed to install/use Node 20. Falling back to a per-user portable install."
        }
    }
    elseif (Test-CommandExists "nvm") {
        Write-Host "[install] Detected nvm. Using nvm to install/use Node 20..." -ForegroundColor Yellow
        try {
            Start-Process -FilePath "nvm" -ArgumentList "install", "20.11.1" -Wait -NoNewWindow
            Start-Process -FilePath "nvm" -ArgumentList "use", "20.11.1" -Wait -NoNewWindow
            # nvm-windows updates the symlink at C:\Program Files\nodejs, but the current PATH might need to point to it
            $env:PATH = "C:\Program Files\nodejs\;$env:PATH"
            if (Test-CommandExists "node") {
                $nodeVersion = node --version
                $cleanVersion = $nodeVersion.TrimStart('v')
                $majorVersionStr = $cleanVersion.Split('.')[0]
                $majorVersion = 0
                if ([int]::TryParse($majorVersionStr, [ref]$majorVersion) -and $majorVersion -ge 20) {
                    Write-Host "[install] Node.js updated successfully via nvm: $nodeVersion" -ForegroundColor Green
                    $installNode = $false
                }
            }
        } catch {
            Write-Warning "nvm failed to install/use Node 20. Falling back to a per-user portable install."
        }
    }
}

if ($installNode) {
    # Per-user portable install (no admin): download the official ZIP and unpack it
    # under %LOCALAPPDATA%, then put it on the user PATH. Pinned LTS — bump
    # periodically as new Node 20.x releases land.
    $nodeVer = "v20.11.1"
    $nodeDist = "node-$nodeVer-win-x64"
    $nodeUrl = "https://nodejs.org/dist/$nodeVer/$nodeDist.zip"
    $nodeZip = "$env:TEMP\$nodeDist.zip"
    $nodeHome = "$env:LOCALAPPDATA\Programs\nodejs"
    $nodeStage = "$env:TEMP\luminary-node"

    Write-Host "[install] Downloading Node.js $nodeVer (per-user portable)..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri $nodeUrl -OutFile $nodeZip -UseBasicParsing

    Write-Host "[install] Extracting Node.js to $nodeHome ..." -ForegroundColor Gray
    if (Test-Path $nodeStage) { Remove-Item -Recurse -Force $nodeStage }
    Expand-Archive -Path $nodeZip -DestinationPath $nodeStage -Force
    if (Test-Path $nodeHome) { Remove-Item -Recurse -Force $nodeHome }
    $nodeParent = Split-Path -Parent $nodeHome
    if (-not (Test-Path $nodeParent)) { New-Item -ItemType Directory -Path $nodeParent -Force | Out-Null }
    Move-Item -Path "$nodeStage\$nodeDist" -Destination $nodeHome -Force
    Remove-Item -Recurse -Force $nodeStage -ErrorAction SilentlyContinue

    Add-UserPath $nodeHome

    if (Test-CommandExists "node") {
        $newNodeVersion = node --version
        $cleanVersion = $newNodeVersion.TrimStart('v')
        $majorVersionStr = $cleanVersion.Split('.')[0]
        $majorVersion = 0
        if ([int]::TryParse($majorVersionStr, [ref]$majorVersion) -and $majorVersion -ge 20) {
            Write-Host "[install] Node.js installed successfully: $newNodeVersion" -ForegroundColor Green
        } else {
            Write-Warning "Node.js was installed to $nodeHome, but the active version in this shell is still $newNodeVersion (requires >= 20)."
            $activeNodePath = (Get-Command node -ErrorAction SilentlyContinue).Source
            Write-Warning "Active node binary is resolved at: '$activeNodePath'"
            if ($activeNodePath -and $activeNodePath -notlike "*$nodeHome*") {
                Write-Warning "An older Node on your PATH is overriding the new install. Remove it, or ensure '$nodeHome' is earlier in your user PATH."
            } else {
                Write-Warning "Please close this PowerShell console, open a new window, and run the script again to pick up the updated PATH."
            }
        }
    } else {
        Write-Warning "Node.js was extracted to $nodeHome, but is not yet on the PATH. Open a new PowerShell window and re-run."
    }
}

# ---------------------------------------------------------------------------
# 4. Install uv (if missing)
# ---------------------------------------------------------------------------
if (Test-CommandExists "uv") {
    $uvVersion = uv --version
    Write-Host "[install] uv is already installed: $uvVersion" -ForegroundColor Green
} else {
    Write-Host "[install] Installing uv (Python package manager)..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

    Add-UserPath "$env:USERPROFILE\.local\bin"

    if (Test-CommandExists "uv") {
        Write-Host "[install] uv installed successfully!" -ForegroundColor Green
    } else {
        Write-Warning "uv was installed, but is not yet on the PATH."
    }
}

# ---------------------------------------------------------------------------
# 5. Install & Run Ollama (if missing)
# ---------------------------------------------------------------------------
if (Test-CommandExists "ollama") {
    $ollamaVersion = ollama --version 2>&1
    Write-Host "[install] Ollama is already installed: $ollamaVersion" -ForegroundColor Green
} else {
    Write-Host "[install] Ollama not found. Installing Ollama silently..." -ForegroundColor Yellow
    $ollamaUrl = "https://ollama.com/download/OllamaSetup.exe"
    $ollamaPath = "$env:TEMP\OllamaSetup.exe"
    
    Write-Host "[install] Downloading Ollama installer..." -ForegroundColor Gray
    Invoke-WebRequest -Uri $ollamaUrl -OutFile $ollamaPath -UseBasicParsing
    
    Write-Host "[install] Running installer (per-user, no admin)..." -ForegroundColor Gray
    # OllamaSetup.exe is an Inno Setup installer with two documented hang modes
    # under a bare `-Wait`:
    #   1. Inno's /SILENT still shows message boxes (restart prompt, "Ollama is
    #      running"), which can open BEHIND the console and wait for a click
    #      forever. /SUPPRESSMSGBOXES auto-answers them; /VERYSILENT hides the
    #      progress window too.
    #   2. Its post-install step launches the Ollama tray app, and the setup
    #      process can stay alive as long as the tray app runs -- so waiting on
    #      setup exit blocks forever even though the install succeeded.
    # Therefore: bounded wait, then judge success by the binary on disk.
    $ollamaLog = "$env:TEMP\OllamaSetup.log"
    $ollamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    $setupProc = Start-Process -FilePath $ollamaPath `
        -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$ollamaLog`"" `
        -PassThru

    $timeoutMinutes = 10
    if (-not $setupProc.WaitForExit($timeoutMinutes * 60 * 1000)) {
        if (Test-Path $ollamaExe) {
            # Files are installed; setup is only babysitting the tray app it
            # launched. Kill the lingering setup process (not the tray app) and
            # move on.
            Write-Host "[install] Ollama files are installed; the setup process did not exit (it waits on the tray app). Continuing." -ForegroundColor Yellow
            Stop-Process -Id $setupProc.Id -Force -ErrorAction SilentlyContinue
        } else {
            Stop-Process -Id $setupProc.Id -Force -ErrorAction SilentlyContinue
            Write-Error "Ollama installer did not finish within $timeoutMinutes minutes and no binary was found at $ollamaExe. See the installer log at $ollamaLog, or install manually from https://ollama.com/download and re-run this script."
        }
    }

    Add-UserPath "$env:LOCALAPPDATA\Programs\Ollama"

    if (Test-CommandExists "ollama") {
        Write-Host "[install] Ollama installed successfully." -ForegroundColor Green
    } else {
        Write-Warning "Ollama was installed but is not yet on the PATH. Open a new PowerShell window and re-run this script."
    }
}

# Check if port 11434 is already active
$portActive = Get-NetTCPConnection -LocalPort 11434 -ErrorAction SilentlyContinue
if ($portActive) {
    Write-Host "[install] Ollama is already running on port 11434." -ForegroundColor Green
} else {
    Write-Host "[install] Starting Ollama background server..." -ForegroundColor Yellow
    try {
        Start-Process -FilePath "ollama" -ArgumentList "serve" -NoNewWindow
        Start-Sleep -Seconds 5
    } catch {
        Write-Warning "Failed to start Ollama automatically. You may need to run 'ollama serve' manually."
    }
}

# Memory profile first: the model block below reads $LumProfile, $MemGB and
# $MaxLoaded, and an
# undefined variable compares as 0 in PowerShell -- so a later definition would
# silently pick the single-model default on every profile.
$MemGB = 0
try {
    $MemGB = [int][math]::Floor((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
} catch {
    Write-Host "[install] Could not read installed RAM; assuming a small machine." -ForegroundColor Gray
}

# NOT $Profile: that is an automatic variable holding the user's profile path.
$LumProfile = $env:LUMINARY_PROFILE
# Validated rather than passed through. The `switch` below has a `default` arm,
# so an unrecognised value silently took the single-model branch and was then
# written verbatim to backend/.env, where the backend rejects it and re-sizes
# from host RAM -- installer and app disagreeing with nothing said. Matched
# case-sensitively so this agrees with install.sh, whose `case` is exact.
# `low` and `public` named the one-model profile, retired when 16GB became the
# supported floor. Both are still accepted and resolve to `standard`, matching
# `memory_profile._LEGACY_ALIASES`, so an installed .env keeps working.
if ($LumProfile -ceq "low" -or $LumProfile -ceq "public") { $LumProfile = "standard" }
if ($LumProfile -and -not ($LumProfile -cin @("standard", "performance"))) {
    Write-Host "[install] LUMINARY_PROFILE='$LumProfile' is not one of: standard, performance (low/public map to standard)." -ForegroundColor Red
    Write-Host "[install] It would be written to backend/.env, where the backend rejects it and" -ForegroundColor Red
    Write-Host "[install] re-sizes from host RAM -- so the installer and the app would disagree." -ForegroundColor Red
    exit 1
}
# 16GB is the supported floor. A smaller machine gets `standard` too and is told
# it is under the floor, rather than silently narrowed to one resident model --
# which is what made the experience fall flat off macOS.
if (-not $LumProfile) {
    if ($MemGB -gt 24)      { $LumProfile = "performance" }
    else                    { $LumProfile = "standard" }
}
if ($MemGB -gt 0 -and $MemGB -lt 16) {
    Write-Host "[install] This machine reports ${MemGB}GB. Luminary is tuned for 16GB and up:" -ForegroundColor Yellow
    Write-Host "[install] ingestion, chat and flashcard generation will be slower here." -ForegroundColor Yellow
}

switch ($LumProfile) {
    "performance" { $MaxLoaded = 2; $NumParallel = 4; $VisionConcurrency = 4 }
    "standard"    { $MaxLoaded = 2; $NumParallel = 2; $VisionConcurrency = 2 }
    default       { $MaxLoaded = 1; $NumParallel = 1; $VisionConcurrency = 1 }
}
Write-Host "[install] ${MemGB}GB RAM -> '$LumProfile' profile (OLLAMA_NUM_PARALLEL=$NumParallel)" -ForegroundColor Yellow

# Pull the chat model, chosen from the memory profile.
#
# llama3.2 was the default on the strength of an HHEM faithfulness comparison
# (d2l + book, 2026-07-23). That comparison is no longer admissible -- a
# cross-model HHEM delta is a style artifact, which is why it may not gate a
# model decision -- and the structural matrix (2026-08-16) put qwen3.5:4b ahead
# on every gating metric.
#
# The profile decides because "public" keeps ONE model loaded. A text-only chat
# model there leaves the vision role with nothing the machine can hold: loading a
# second model evicts the one answering questions. qwen3.5:4b reads figures at
# 3.21GB resident, the same as its text footprint, so one model covers every role.
# Must stay equal to model_registry.GENERALIST_PREFERENCE[0]; the guard is
# backend/tests/test_installer_models.py.
#
# NOTE: try/catch cannot detect native command failure in PS 5.1 -- non-zero
# exit codes do not throw -- so check $LASTEXITCODE instead.
$PublicGeneralist = "qwen3.5:4b"
# The strongest text model, pulled only on `performance`: 9.67GB resident, and it
# does not read figures, so it is always a second model alongside the reader.
$LargeTextModel = "qwen2.5:14b-instruct"
# The band is a policy choice; this is a measurement. The backend keeps its
# resident set to half of RAM, and this model plus the generalist is 12.88GB, so
# the pair needs 25.76GB -- 25GB fails and 26GB fits. Below this the installer
# downloads 9.67GB the backend then refuses to load. Mirrors
# LARGE_TEXT_MIN_RAM_GB in install.sh; test_installer_models.py fails on drift.
$LargeTextMinRamGB = 26

$chatModel = $env:LUMINARY_CHAT_MODEL
$visionModel = $env:LUMINARY_VISION_MODEL
if (-not $chatModel) {
    if ($LumProfile -eq "performance" -and $MemGB -ge $LargeTextMinRamGB) {
        # The only band with room for a text model that cannot read figures.
        $chatModel = $LargeTextModel
    } else {
        $chatModel = $PublicGeneralist
    }
}
# Outside the block above on purpose. While it was nested inside
# `if (-not $chatModel)`, setting LUMINARY_CHAT_MODEL alone skipped it, and a
# host with room for a reader pulled none -- figures then failed quietly, which
# is the mode this profile exists to avoid.
if ((-not $visionModel) -and $MaxLoaded -gt 1 -and $chatModel -ne $PublicGeneralist) {
    $visionModel = $PublicGeneralist
}
if (Test-CommandExists "ollama") {
    Write-Host "[install] Pulling chat model $chatModel (this can take a few minutes)..." -ForegroundColor Yellow
    ollama pull $chatModel
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARNING] Failed to pull $chatModel. If you are behind a corporate VPN/Proxy, disconnect or configure your system proxy settings, then run 'ollama pull $chatModel' manually." -ForegroundColor Red
    }
} else {
    Write-Warning "ollama is not on the PATH in this session. Open a new PowerShell window and run: ollama pull $chatModel"
}

# The vision model, already resolved above from the profile and installed RAM.
# It was re-read from the environment here, which discarded that decision and
# left the pull disabled on every machine that had not set the variable.
if ($visionModel -and (Test-CommandExists "ollama")) {
    Write-Host "[install] Pulling vision model $visionModel (this can take several minutes)..." -ForegroundColor Yellow
    ollama pull $visionModel
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARNING] Failed to pull vision model $visionModel. Add it later with: ollama pull $visionModel" -ForegroundColor Red
    }
}

# ---------------------------------------------------------------------------
# 6. Install Backend & Frontend dependencies
# ---------------------------------------------------------------------------
$RepoRoot = (Get-Item -Path $PSScriptRoot).Parent.FullName

# Backend sync
Write-Host "[install] Installing backend dependencies..." -ForegroundColor Yellow
Set-Location -Path "$RepoRoot\backend"
# `full` adds yt-dlp and the tree-sitter grammars. The article path
# (trafilatura, cloudscraper) moved to base dependencies, because web_ingest is
# a `public` surface and the Docker image installs base only -- it was shipping
# without the libraries its own manifest advertised.
uv sync --no-default-groups --group full

# Frontend build
Write-Host "[install] Installing frontend dependencies..." -ForegroundColor Yellow
Set-Location -Path "$RepoRoot\frontend"

# We must run npm using npm.cmd on Windows to prevent execution issues
$npmCommand = "npm.cmd"
if (-not (Test-CommandExists $npmCommand)) {
    $npmCommand = "npm"
}

Write-Host "[install] Running npm ci..." -ForegroundColor Gray
$npmCiFailed = $false
try {
    & $npmCommand ci --legacy-peer-deps
    if ($LASTEXITCODE -ne 0) { $npmCiFailed = $true }
} catch {
    $npmCiFailed = $true
}

if ($npmCiFailed) {
    Write-Host "[install] npm ci failed. Trying npm install instead..." -ForegroundColor Yellow
    try {
        & $npmCommand install --no-audit --no-fund --legacy-peer-deps
        if ($LASTEXITCODE -ne 0) {
            Write-Error "npm install failed. Frontend dependencies could not be installed."
        }
    } catch {
        Write-Error "npm install failed. Frontend dependencies could not be installed."
    }
}

Write-Host "[install] Building production SPA..." -ForegroundColor Yellow
$env:VITE_LUMINARY_MODE="public"
$env:VITE_API_BASE="/api"
try {
    & $npmCommand run build
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Production build failed. Please ensure Node >= 20 is active in your terminal."
    }
} catch {
    Write-Error "Production build failed. Please ensure Node >= 20 is active in your terminal."
}

# ---------------------------------------------------------------------------
# 6b. Performance profile
# ---------------------------------------------------------------------------
# The profile itself is resolved further up, before the model pull that depends
# on it. Parallelism is a memory decision: one KV cache per slot.
Set-Location -Path $RepoRoot

# Persist for the backend, which reads backend\.env and sizes its enrichment
# concurrency from OLLAMA_NUM_PARALLEL.
$EnvFile = "$RepoRoot\backend\.env"
if (-not (Test-Path $EnvFile)) { New-Item -ItemType File -Path $EnvFile -Force | Out-Null }
$EnvLines = @(Get-Content -Path $EnvFile -ErrorAction SilentlyContinue)

function Set-EnvLine($Lines, $Key, $Value) {
    # @() matters: Where-Object yields $null or a bare string, and `+=` on
    # either is not an append.
    $kept = @($Lines | Where-Object { $_ -notmatch ('^' + [regex]::Escape($Key) + '=') })
    return $kept + "$Key=$Value"
}

$EnvLines = Set-EnvLine $EnvLines "OLLAMA_NUM_PARALLEL" $NumParallel
$EnvLines = Set-EnvLine $EnvLines "ENRICHMENT_VISION_CONCURRENCY" $VisionConcurrency
# The profile in the backend's vocabulary, so it does not size a different one
# from host RAM and resolve to models this install never pulled. "low" is
# canonical; "public" survives only as a legacy alias.
$BackendProfile = if ($LumProfile -eq "public") { "low" } else { $LumProfile }
$EnvLines = Set-EnvLine $EnvLines "LUMINARY_MEMORY_PROFILE" $BackendProfile
# The models this installer actually pulled. Leaving them unset lets the
# backend resolve its own host-aware default, which is not the model on disk
# -- it fails at the user's first question instead of here. install.sh and
# bootstrap.sh already close this gap; test_installer_models.py checks this
# script pins the same two keys.
$EnvLines = Set-EnvLine $EnvLines "LITELLM_DEFAULT_MODEL" "ollama/$chatModel"
$visionModelForEnv = if ($visionModel) { $visionModel } else { $chatModel }
$EnvLines = Set-EnvLine $EnvLines "VISION_MODEL" "ollama/$visionModelForEnv"
Set-Content -Path $EnvFile -Value $EnvLines -Encoding UTF8

# Ollama on Windows reads its own knobs from the user environment, and the
# already-running server does not pick them up until it restarts.
[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS", "$MaxLoaded", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL", "$NumParallel", "User")
# llama.cpp's prompt cache is left at 8192MB by default on every host, which is
# more than most machines can spare. A saved prompt state measures 105-206MB, so
# 512MB holds the two or three recent prompts reuse actually draws on.
[Environment]::SetEnvironmentVariable("LLAMA_ARG_CACHE_RAM", "512", "User")
# Residency must be set on the server: LiteLLM's `ollama/` completion path folds
# a per-call keep_alive into `options`, where Ollama rejects it, so the backend
# cannot ask for this. Without it the model unloads on Ollama's 5-minute default
# and the next question pays a full reload.
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "30m", "User")
Write-Host "[install] Restart Ollama for the server-side profile to take effect." -ForegroundColor Gray

# ---------------------------------------------------------------------------
# 7. Create local startup scripts
# ---------------------------------------------------------------------------
Set-Location -Path $RepoRoot

# Literal here-string (@'...'@): nothing is expanded at generation time, so the
# script below is written to start.ps1 verbatim. Mirrors start.sh: launch the
# server, poll /health until ready, print a banner, then stay attached.
$startScriptContent = @'
# start.ps1 — Startup script for Luminary
$ErrorActionPreference = "Stop"
Set-Location -Path "$PSScriptRoot\backend"
$env:DATA_DIR = "$PSScriptRoot\.luminary"
$env:LUMINARY_MODE = "public"
$port = 7820

Write-Host "Starting Luminary... (first run downloads models and can take a few minutes)" -ForegroundColor Cyan
# --no-sync is load-bearing: `uv run` resolves DEFAULT groups (dev, full,
# media) before executing, so every launch reinstalled what install.ps1
# deliberately left out -- faster-whisper among them, whose PyAV wheels carry
# GPL binaries -- and made startup need the network.
$proc = Start-Process -FilePath "uv" `
    -ArgumentList "run", "--no-sync", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$port" `
    -NoNewWindow -PassThru

# Poll /health so the "ready" banner reflects reality. First run downloads models,
# so allow generous time; only claim ready when /health actually answers 200.
$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    if ($proc.HasExited) {
        Write-Error "Backend exited before becoming ready (exit code $($proc.ExitCode)). Scroll up for the error."
    }
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:$port/health" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
}

if ($ready) {
    Write-Host "  Luminary is ready  ->  open http://localhost:$port" -ForegroundColor Green
} else {
    Write-Warning "  Still downloading models -- leave this window open; it'll be ready at http://localhost:$port shortly."
}
try {
    Wait-Process -Id $proc.Id
} finally {
    # Kill the whole tree: $proc is the `uv` launcher; uvicorn/python run as children.
    if (-not $proc.HasExited) { taskkill /PID $proc.Id /T /F 2>$null | Out-Null }
}
'@

$startScriptContent | Out-File -FilePath "$RepoRoot\start.ps1" -Encoding utf8

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "       Installation Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host "Setup is done. To start the app (now and every time), run:"
Write-Host "  .\start.ps1" -ForegroundColor Yellow
Write-Host "Wait for 'Luminary is ready', then open http://localhost:7820"
Write-Host ""
Write-Host "If a tool was reported 'not on PATH' above, open a NEW PowerShell"
Write-Host "window first so the updated PATH takes effect."
if ($visionModel) {
    Write-Host "Models pulled: $chatModel and $visionModel. $visionModel reads figures." -ForegroundColor Gray
} else {
    Write-Host "$chatModel answers questions and reads figures, so image analysis works already." -ForegroundColor Gray
    Write-Host "A second model would evict it rather than adding to it on this machine." -ForegroundColor Gray
}
Write-Host "=========================================" -ForegroundColor Green
