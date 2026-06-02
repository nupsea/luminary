# install.ps1 — Automated native Windows installer for Luminary.
#
# Safe to re-run. Handles dependencies and corporate proxies gracefully.
#
# Usage:
#   Open PowerShell as Administrator and run:
#   Set-ExecutionPolicy Bypass -Scope Process -Force; .\scripts\install.ps1

$ErrorActionPreference = "Stop"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "   Starting Luminary Windows Installer" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 0. Global Corporate Proxy / SSL Bypass Settings
# ---------------------------------------------------------------------------
Write-Host "[install] Configuring SSL/TLS bypass variables for corporate networks..." -ForegroundColor Gray
$env:UV_SYSTEM_CERTS = "true"
$env:UV_INSECURE_HOST = "pypi.org files.pythonhosted.org pythonhosted.org"
try {
    Start-Process -FilePath "npm" -ArgumentList "config", "set", "strict-ssl", "false" -Wait -NoNewWindow
} catch {}

# Helper to check if a command exists
function Test-CommandExists($Command) {
    return (Get-Command $Command -ErrorAction SilentlyContinue) -ne $null
}

# ---------------------------------------------------------------------------
# 2. Install Python 3.13 (if missing)
# ---------------------------------------------------------------------------
if (Test-CommandExists "python") {
    $pyVersion = python --version 2>&1
    Write-Host "[install] Python is already installed: $pyVersion" -ForegroundColor Green
} else {
    Write-Host "[install] Python not found. Installing Python 3.13 silently..." -ForegroundColor Yellow
    $pyUrl = "https://www.python.org/ftp/python/3.13.0/python-3.13.0-amd64.exe"
    $pyPath = "$env:TEMP\python-3.13.0.exe"
    
    Write-Host "[install] Downloading Python installer..." -ForegroundColor Gray
    Invoke-WebRequest -Uri $pyUrl -OutFile $pyPath
    
    Write-Host "[install] Running installer (this may take a minute)..." -ForegroundColor Gray
    Start-Process -FilePath $pyPath -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1" -Wait
    
    # Update PATH for the current session
    $env:PATH = "C:\Program Files\Python313\;C:\Program Files\Python313\Scripts\;$env:PATH"
    
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
    Write-Host "[install] Installing Node.js 20 LTS silently..." -ForegroundColor Yellow
    $nodeUrl = "https://nodejs.org/dist/v20.11.1/node-v20.11.1-x64.msi"
    $nodePath = "$env:TEMP\node-v20.msi"
    
    Write-Host "[install] Downloading Node.js installer..." -ForegroundColor Gray
    Invoke-WebRequest -Uri $nodeUrl -OutFile $nodePath
    
    Write-Host "[install] Running installer (this may take a minute)..." -ForegroundColor Gray
    Start-Process -FilePath "msiexec.exe" -ArgumentList "/i", "`"$nodePath`"", "/quiet", "/norestart" -Wait
    
    # Update PATH for the current session
    $env:PATH = "C:\Program Files\nodejs\;$env:PATH"
    
    if (Test-CommandExists "node") {
        $newNodeVersion = node --version
        Write-Host "[install] Node.js installed successfully: $newNodeVersion" -ForegroundColor Green
    } else {
        Write-Warning "Node.js was installed, but is not yet on the PATH. You may need to restart PowerShell after installation."
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
    
    # Update PATH for current session
    $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
    
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
    Invoke-WebRequest -Uri $ollamaUrl -OutFile $ollamaPath
    
    Write-Host "[install] Running installer..." -ForegroundColor Gray
    Start-Process -FilePath $ollamaPath -ArgumentList "/silent" -Wait
    
    # Update PATH for current session
    $env:PATH = "$env:LOCALAPPDATA\Programs\Ollama\;$env:PATH"
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

# Pull models
try {
    Write-Host "[install] Pulling Llama 3.2 chat model (this can take a few minutes)..." -ForegroundColor Yellow
    ollama pull llama3.2
} catch {
    Write-Host "[WARNING] Ollama failed to pull models. If you are behind a corporate VPN/Proxy, please disconnect or configure your system proxy settings and try running 'ollama pull llama3.2' manually." -ForegroundColor Red
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
try {
    Write-Host "[install] Running npm ci..." -ForegroundColor Gray
    npm ci --legacy-peer-deps
} catch {
    Write-Host "[install] npm ci failed. Trying npm install instead..." -ForegroundColor Yellow
    npm install --no-audit --no-fund --legacy-peer-deps
}

Write-Host "[install] Building production SPA..." -ForegroundColor Yellow
$env:VITE_SURFACE_TIER="public"
$env:VITE_API_BASE="/api"
npm run build

# ---------------------------------------------------------------------------
# 7. Create local startup scripts
# ---------------------------------------------------------------------------
Set-Location -Path $RepoRoot

$startScriptContent = @"
# start.ps1 — Startup script for Luminary
`$ErrorActionPreference = "Stop"
Set-Location -Path "`$PSScriptRoot\backend"
`$env:DATA_DIR="`$PSScriptRoot\.luminary"
Write-Host "Starting Luminary Backend on http://localhost:7820 ..." -ForegroundColor Green
uv run uvicorn app.main:app --host 0.0.0.0 --port 7820
"@

$startScriptContent | Out-File -FilePath "$RepoRoot\start.ps1" -Encoding utf8

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "       Installation Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host "To start the application, run:"
Write-Host "  .\start.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "Then open http://localhost:7820 in your browser."
Write-Host "=========================================" -ForegroundColor Green
