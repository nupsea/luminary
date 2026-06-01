# install.ps1 — Automated native Windows installer for Luminary.
#
# Safe to re-run. Handles dependencies gracefully.
#
# Usage:
#   Open PowerShell as Administrator and run:
#   Set-ExecutionPolicy Bypass -Scope Process -Force; .\scripts\install.ps1

$ErrorActionPreference = "Stop"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "   Starting Luminary Windows Installer" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 1. Helper to check if a command exists
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
# 3. Install Node.js (if missing)
# ---------------------------------------------------------------------------
if (Test-CommandExists "node") {
    $nodeVersion = node --version
    Write-Host "[install] Node.js is already installed: $nodeVersion" -ForegroundColor Green
} else {
    Write-Host "[install] Node.js not found. Installing Node.js 20 LTS silently..." -ForegroundColor Yellow
    $nodeUrl = "https://nodejs.org/dist/v20.11.1/node-v20.11.1-x64.msi"
    $nodePath = "$env:TEMP\node-v20.msi"
    
    Write-Host "[install] Downloading Node.js installer..." -ForegroundColor Gray
    Invoke-WebRequest -Uri $nodeUrl -OutFile $nodePath
    
    Write-Host "[install] Running installer (this may take a minute)..." -ForegroundColor Gray
    Start-Process -FilePath "msiexec.exe" -ArgumentList "/i", "`"$nodePath`"", "/quiet", "/norestart" -Wait
    
    # Update PATH for the current session
    $env:PATH = "C:\Program Files\nodejs\;$env:PATH"
    
    if (Test-CommandExists "node") {
        Write-Host "[install] Node.js installed successfully!" -ForegroundColor Green
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

# Ensure Ollama server is running in the background
$ollamaRunning = $false
try {
    $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/version" -TimeoutSec 2
    $ollamaRunning = $true
} catch {
    # Not running
}

if (-not $ollamaRunning) {
    Write-Host "[install] Starting Ollama background server..." -ForegroundColor Yellow
    Start-Process -FilePath "ollama" -ArgumentList "serve" -NoNewWindow
    Start-Sleep -Seconds 5
}

# Pull models
Write-Host "[install] Pulling Gemma4 chat model (this can take a few minutes)..." -ForegroundColor Yellow
ollama pull gemma4
Write-Host "[install] Pulling Llava vision model (this can take a few minutes)..." -ForegroundColor Yellow
ollama pull llava:7b

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
npm ci

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
