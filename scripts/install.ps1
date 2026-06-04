# install.ps1 — Automated native Windows installer for Luminary.
#
# Safe to re-run. Handles dependencies and corporate proxies gracefully.
#
# Usage:
#   Open PowerShell as Administrator and run:
#   Set-ExecutionPolicy Bypass -Scope Process -Force; .\scripts\install.ps1

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Verify Administrator Privileges
# ---------------------------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "This installer script must be run in a PowerShell session opened as Administrator. Please right-click PowerShell, choose 'Run as Administrator', and try again."
}

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
            Write-Warning "fnm failed to install/use Node 20. Falling back to MSI installer."
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
            Write-Warning "nvm failed to install/use Node 20. Falling back to MSI installer."
        }
    }
}

if ($installNode) {
    Write-Host "[install] Downloading Node.js 20 LTS installer..." -ForegroundColor Yellow
    $nodeUrl = "https://nodejs.org/dist/v20.11.1/node-v20.11.1-x64.msi"
    $nodePath = "$env:TEMP\node-v20.msi"
    
    Invoke-WebRequest -Uri $nodeUrl -OutFile $nodePath
    
    Write-Host "[install] Running installer silently (this may take a minute)..." -ForegroundColor Gray
    $process = Start-Process -FilePath "msiexec.exe" -ArgumentList "/i", "`"$nodePath`"", "/quiet", "/norestart" -Wait -PassThru
    
    # Check if installer failed
    if ($process.ExitCode -ne 0) {
        Write-Warning "Node.js MSI installer exited with code $($process.ExitCode)."
    }

    # Prepend default Node.js installation directory to PATH
    $env:PATH = "C:\Program Files\nodejs\;$env:PATH"
    
    if (Test-CommandExists "node") {
        $newNodeVersion = node --version
        $cleanVersion = $newNodeVersion.TrimStart('v')
        $majorVersionStr = $cleanVersion.Split('.')[0]
        $majorVersion = 0
        if ([int]::TryParse($majorVersionStr, [ref]$majorVersion) -and $majorVersion -ge 20) {
            Write-Host "[install] Node.js installed/updated successfully: $newNodeVersion" -ForegroundColor Green
        } else {
            Write-Warning "Node.js was installed, but the active version in this shell is still $newNodeVersion (requires >= 20)."
            $activeNodePath = (Get-Command node -ErrorAction SilentlyContinue).Source
            Write-Warning "Active node binary is resolved at: '$activeNodePath'"
            if ($activeNodePath -and $activeNodePath -notlike "*C:\Program Files\nodejs*") {
                Write-Warning "This old Node path is overriding the new Node.js 20 installation. Please uninstall the old version or ensure 'C:\Program Files\nodejs\' is placed higher in your system/user PATH environment variable."
            } else {
                Write-Warning "Please close this PowerShell console, open a new Administrator PowerShell window, and run the script again to pick up the updated PATH."
            }
        }
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
$env:VITE_SURFACE_TIER="public"
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

$startScriptContent = @"
# start.ps1 — Startup script for Luminary
`$ErrorActionPreference = "Stop"
Set-Location -Path "`$PSScriptRoot\backend"
`$env:DATA_DIR="`$PSScriptRoot\.luminary"
`$env:LUMINARY_MODE="prod"
`$env:LUMINARY_SURFACE_TIER="public"
Write-Host "Starting Luminary Backend on http://localhost:7820 ..." -ForegroundColor Green
uv run uvicorn app.main:app --host 127.0.0.1 --port 7820
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
