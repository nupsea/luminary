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

# Pull the chat model
try {
    Write-Host "[install] Pulling Llama 3.2 chat model (this can take a few minutes)..." -ForegroundColor Yellow
    ollama pull llama3.2
} catch {
    Write-Host "[WARNING] Ollama failed to pull models. If you are behind a corporate VPN/Proxy, please disconnect or configure your system proxy settings and try running 'ollama pull llama3.2' manually." -ForegroundColor Red
}

# Optional vision model (labs-gated; powers image/figure analysis). Skipped by
# default — it's a large download. Choose via the LUMINARY_VISION_MODEL env var,
# the prompt below, or install it later with: ollama pull llava:7b
$visionModel = $env:LUMINARY_VISION_MODEL
if (-not $visionModel -and [Environment]::UserInteractive) {
    $answer = Read-Host "[install] Install the optional vision model (llava:7b, ~4.7 GB) for image/figure analysis? [y/N]"
    if ($answer -match '^(y|yes)$') { $visionModel = "llava:7b" }
}
if ($visionModel) {
    try {
        Write-Host "[install] Pulling vision model $visionModel (this can take several minutes)..." -ForegroundColor Yellow
        ollama pull $visionModel
    } catch {
        Write-Host "[WARNING] Failed to pull vision model $visionModel. Add it later with: ollama pull $visionModel" -ForegroundColor Red
    }
} else {
    Write-Host "[install] Skipping vision model. To enable image/figure analysis later, run: ollama pull llava:7b" -ForegroundColor Gray
}

# ---------------------------------------------------------------------------
# 6. Install Backend & Frontend dependencies
# ---------------------------------------------------------------------------
$RepoRoot = (Get-Item -Path $PSScriptRoot).Parent.FullName

# Backend sync
Write-Host "[install] Installing backend dependencies..." -ForegroundColor Yellow
Set-Location -Path "$RepoRoot\backend"
uv sync --no-default-groups

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

Write-Host "Starting Luminary on http://localhost:$port ..." -ForegroundColor Cyan
$proc = Start-Process -FilePath "uv" `
    -ArgumentList "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$port" `
    -NoNewWindow -PassThru

for ($i = 0; $i -lt 60; $i++) {
    if ($proc.HasExited) {
        Write-Error "Backend exited before becoming ready (exit code $($proc.ExitCode))."
    }
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:$port/health" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { break }
    } catch {}
    Start-Sleep -Seconds 1
}

Write-Host "  Luminary is ready  --  http://localhost:$port" -ForegroundColor Green
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
Write-Host "Installed per-user (no admin). If a tool is reported 'not on PATH'"
Write-Host "above, open a NEW PowerShell window so the updated PATH takes effect."
Write-Host ""
Write-Host "To start the application, run:"
Write-Host "  .\start.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "Then open http://localhost:7820 in your browser."
Write-Host "Optional: enable image/figure analysis later with 'ollama pull llava:7b'."
Write-Host "=========================================" -ForegroundColor Green
