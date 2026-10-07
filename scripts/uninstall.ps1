# uninstall.ps1 — undo scripts\install.ps1 for this checkout.
#
# Removes what lives in the checkout (backend\.venv, frontend\node_modules,
# frontend\dist, start.ps1, the installer's keys in backend\.env) and whatever
# install.ps1 recorded in .install-manifest. A tool that was already on the
# machine is never recorded, so it is never removed; unrecorded leftovers
# Luminary may have added are listed at the end for the user to check. The
# library (.luminary\) is kept unless -PurgeData.
#
# Usage: .\scripts\uninstall.ps1 [-DryRun] [-Yes] [-PurgeData]

param([switch]$DryRun, [switch]$Yes, [switch]$PurgeData)

$ErrorActionPreference = "Stop"

$RepoRoot = (Get-Item -Path $PSScriptRoot).Parent.FullName
$Manifest = Join-Path $RepoRoot ".install-manifest"
$EnvFile = [IO.Path]::Combine($RepoRoot, "backend", ".env")
$BackendPort = 7820
$NodeHome = [IO.Path]::Combine("$env:LOCALAPPDATA", "Programs", "nodejs")
$OllamaHome = [IO.Path]::Combine("$env:LOCALAPPDATA", "Programs", "Ollama")
$UvBin = [IO.Path]::Combine("$env:USERPROFILE", ".local", "bin")

# Keys install.ps1 writes into backend\.env; any other line there is the user's.
# test_uninstall_ps1.py fails if this drifts from install.ps1's Set-EnvLine calls.
$InstallerEnvKeys = @("OLLAMA_NUM_PARALLEL", "ENRICHMENT_VISION_CONCURRENCY", "LUMINARY_MEMORY_PROFILE", "LITELLM_DEFAULT_MODEL", "VISION_MODEL")
# User environment variables install.ps1 sets; listed by hand when unrecorded.
$InstallerUserEnv = @("OLLAMA_MAX_LOADED_MODELS", "OLLAMA_NUM_PARALLEL", "LLAMA_ARG_CACHE_RAM", "OLLAMA_KEEP_ALIVE")

function Write-Info($Msg) { Write-Host "[uninstall] $Msg" -ForegroundColor Cyan }
function Write-Warn($Msg) { Write-Host "[uninstall] $Msg" -ForegroundColor Yellow }
function Test-Cmd($Name) { $null -ne (Get-Command $Name -ErrorAction SilentlyContinue) }

$Records = @(if (Test-Path -LiteralPath $Manifest) { Get-Content -LiteralPath $Manifest })
function Test-Recorded($Line) { $Records -contains $Line }
function Get-Recorded($Prefix) {
    $Records | Where-Object { $_.StartsWith($Prefix) } | ForEach-Object { $_.Substring($Prefix.Length) }
}

# PS 5.1 turns a native command's redirected stderr into a terminating error under Stop.
function Invoke-Quiet {
    $ErrorActionPreference = "Continue"
    $rest = @($args | Select-Object -Skip 1)
    & $args[0] @rest 2>$null
}

function Get-SizeText($Path) {
    $bytes = (Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
    if (-not $bytes) { $bytes = (Get-Item -LiteralPath $Path -Force).Length }
    if (-not $bytes) { return "0 MB" }
    return "{0:N0} MB" -f ($bytes / 1MB)
}

# Deleting the venv under a running backend leaves it half-dead holding the DB.
function Test-Listening {
    $client = New-Object System.Net.Sockets.TcpClient
    try { return $client.ConnectAsync("127.0.0.1", $BackendPort).Wait(1000) } catch { return $false } finally { $client.Close() }
}
if (Test-Listening) {
    Write-Host "[uninstall] Something is listening on :$BackendPort -- stop Luminary first, then re-run." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# What to remove: listed first, run only after confirmation.
# ---------------------------------------------------------------------------
$Steps = New-Object System.Collections.Generic.List[object]
function Add-Step($Desc, [scriptblock]$Action, $Arg) {
    $Steps.Add([pscustomobject]@{ Desc = $Desc; Action = $Action; Arg = $Arg })
}

function Remove-Tree($Path) { Remove-Item -LiteralPath $Path -Recurse -Force }

# Walked by hand so .git, .venv and node_modules are pruned, never traversed.
function Find-PythonCaches {
    $queue = New-Object System.Collections.Generic.Queue[string]
    $queue.Enqueue($RepoRoot)
    while ($queue.Count -gt 0) {
        foreach ($d in @(Get-ChildItem -LiteralPath $queue.Dequeue() -Directory -Force -ErrorAction SilentlyContinue)) {
            if ($d.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
            if ($d.Name -in @("__pycache__", ".pytest_cache", ".ruff_cache")) { $d.FullName }
            elseif ($d.Name -notin @(".git", ".venv", "node_modules", ".luminary")) { $queue.Enqueue($d.FullName) }
        }
    }
    $coverage = [IO.Path]::Combine($RepoRoot, "backend", ".coverage")
    if (Test-Path -LiteralPath $coverage) { $coverage }
}

function Test-InstallerEnvLine($Line) {
    foreach ($key in $InstallerEnvKeys) { if ($Line.StartsWith("$key=")) { return $true } }
    return $false
}

function Remove-InstallerEnv {
    $kept = @(Get-Content -LiteralPath $EnvFile | Where-Object { -not (Test-InstallerEnvLine $_) })
    if (@($kept | Where-Object { $_.Trim() }).Count -gt 0) {
        [IO.File]::WriteAllLines($EnvFile, [string[]]$kept)  # UTF-8, no BOM: a BOM would glue itself to the first key
    } else {
        Remove-Item -LiteralPath $EnvFile -Force
    }
}

function Get-PulledModels {
    if (-not (Test-Cmd "ollama")) { return @() }
    return @(Invoke-Quiet ollama list | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s+')[0] } | Where-Object { $_ })
}

function Remove-Model($Model) {
    Invoke-Quiet ollama rm $Model | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "ollama rm $Model exited $LASTEXITCODE" }
}

function Remove-OllamaApp {
    Get-Process -Name "ollama", "ollama app" -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Process -FilePath (Join-Path $OllamaHome "unins000.exe") -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait
}

function Find-PythonUninstall($Version) {
    Get-ChildItem "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall" -ErrorAction SilentlyContinue |
        ForEach-Object { Get-ItemProperty -LiteralPath $_.PSPath } |
        Where-Object { $_.DisplayName -eq "Python $Version (64-bit)" -and $_.QuietUninstallString } |
        Select-Object -First 1
}

function Remove-Python($Entry) {
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$($Entry.QuietUninstallString)`"" -Wait -WindowStyle Hidden
}

# uv's documented uninstall, minus `uv tool dir`: tools installed there since are the user's.
function Remove-Uv {
    $pythons = Invoke-Quiet uv python dir
    Invoke-Quiet uv cache clean | Out-Null
    if ($pythons -and (Test-Path -LiteralPath $pythons)) { Remove-Tree $pythons }
    foreach ($exe in "uv.exe", "uvx.exe", "uvw.exe") {
        Remove-Item -LiteralPath (Join-Path $UvBin $exe) -Force -ErrorAction SilentlyContinue
    }
}

function Set-UserEnvValue($NameValue) {
    [Environment]::SetEnvironmentVariable($NameValue[0], $NameValue[1], "User")
}

# Read and written raw: .NET's getter expands %VARS%, and writing that back
# would replace the user's %USERPROFILE% entries with literal paths.
function Remove-UserPath($Dir) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment", $true)
    try {
        $raw = $key.GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $kept = @($raw -split ';' | Where-Object { $_ -and ($_.TrimEnd('\') -ne $Dir.TrimEnd('\')) })
        $key.SetValue("Path", ($kept -join ';'), [Microsoft.Win32.RegistryValueKind]::ExpandString)
    } finally { $key.Close() }
    # Any user-scope set broadcasts WM_SETTINGCHANGE, so new terminals see the change.
    [Environment]::SetEnvironmentVariable("LUMINARY_UNINSTALL_BROADCAST", $null, "User")
}

function Get-UserPathEntries {
    $raw = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $raw) { return @() }
    return @($raw -split ';' | ForEach-Object { $_.TrimEnd('\') })
}

$Pulled = Get-PulledModels

foreach ($dir in "backend\.venv", "frontend\node_modules", "frontend\dist") {
    $path = Join-Path $RepoRoot $dir
    if (Test-Path -LiteralPath $path) { Add-Step "Remove $dir ($(Get-SizeText $path))" { Remove-Tree $args[0] } $path }
}
$Caches = @(Find-PythonCaches)
if ($Caches.Count -gt 0) {
    Add-Step "Remove Python caches and coverage data (__pycache__, .pytest_cache, .ruff_cache, .coverage)" {
        foreach ($c in $args[0]) { Remove-Tree $c }
    } $Caches
}
$StartScript = Join-Path $RepoRoot "start.ps1"
if (Test-Path -LiteralPath $StartScript) { Add-Step "Remove start.ps1 (generated by the installer)" { Remove-Item -LiteralPath $args[0] -Force } $StartScript }
if ((Test-Path -LiteralPath $EnvFile) -and @(Get-Content -LiteralPath $EnvFile | Where-Object { Test-InstallerEnvLine $_ }).Count -gt 0) {
    Add-Step "Remove the installer's settings from backend\.env (other lines are kept)" { Remove-InstallerEnv } $null
}
$Library = Join-Path $RepoRoot ".luminary"
if ($PurgeData -and (Test-Path -LiteralPath $Library)) {
    Add-Step "DELETE the dev library .luminary\ ($(Get-SizeText $Library)): documents, notes, flashcards" { Remove-Tree $args[0] } $Library
}

if ($Records.Count -gt 0) {
    $models = @(Get-Recorded "model:")
    if ($models.Count -gt 0 -and $Pulled.Count -eq 0) {
        Write-Warn "Ollama is not answering, so the models it pulled cannot be removed now. Start Ollama and re-run to remove: $($models -join ', ')"
    }
    foreach ($model in $models) {
        if ($Pulled -contains $model) { Add-Step "Remove Ollama model $model (pulled by the installer)" { Remove-Model $args[0] } $model }
    }
    if ((Test-Recorded "ollama:app") -and (Test-Path -LiteralPath (Join-Path $OllamaHome "unins000.exe"))) {
        Add-Step "Uninstall Ollama with its own uninstaller (models in ~\.ollama are kept)" { Remove-OllamaApp } $null
    }
    foreach ($ver in @(Get-Recorded "python:")) {
        $entry = Find-PythonUninstall $ver
        if ($entry) { Add-Step "Uninstall Python $ver with its own uninstaller" { Remove-Python $args[0] } $entry }
    }
    if ((Test-Recorded "node:local") -and (Test-Path -LiteralPath $NodeHome)) {
        Add-Step "Remove Node from $NodeHome" { Remove-Tree $args[0] } $NodeHome
    }
    if ((Test-Recorded "uv") -and (Test-Path -LiteralPath (Join-Path $UvBin "uv.exe"))) {
        Add-Step "Uninstall uv: binary, its cache and its Pythons" { Remove-Uv } $null
    }
    $previous = @{}
    foreach ($rec in @(Get-Recorded "prev:")) { $name, $value = $rec.Split('=', 2); $previous[$name] = $value }
    foreach ($rec in @(Get-Recorded "env:")) {
        $name, $value = $rec.Split('=', 2)
        $current = [Environment]::GetEnvironmentVariable($name, "User")
        if ($current -ne $value) {
            if ($current) { Write-Warn "Keeping user variable $name=$($current): changed since the install set it to $value." }
        } elseif ($previous.ContainsKey($name)) {
            Add-Step "Restore user variable $name to your earlier $($previous[$name])" { Set-UserEnvValue $args[0] } @($name, $previous[$name])
        } else {
            Add-Step "Remove user variable $name (set to $value by the installer)" { Set-UserEnvValue $args[0] } @($name, $null)
        }
    }
    $userPath = Get-UserPathEntries
    foreach ($dir in @(Get-Recorded "path:")) {
        if ($userPath -contains $dir.TrimEnd('\')) { Add-Step "Remove $dir from your user PATH" { Remove-UserPath $args[0] } $dir }
    }
    Add-Step "Forget the install record (.install-manifest)" { Remove-Item -LiteralPath $args[0] -Force } $Manifest
}

# ---------------------------------------------------------------------------
# Listed, never run: without a record these may be the user's own.
# ---------------------------------------------------------------------------
# Models this checkout used plus the installer's default: an install that
# predates the manifest pulled one of these.
function Get-CandidateModels {
    if (Test-Path -LiteralPath $EnvFile) {
        Get-Content -LiteralPath $EnvFile | ForEach-Object {
            if ($_ -match '^(LITELLM_DEFAULT_MODEL|VISION_MODEL)=ollama/(.+)$') { $Matches[2].Trim() }
        }
    }
    $installer = Join-Path $PSScriptRoot "install.ps1"
    if (Test-Path -LiteralPath $installer) {
        Get-Content -LiteralPath $installer | ForEach-Object {
            if ($_ -match '^\$PublicGeneralist = "([^"]+)"') { $Matches[1] }
        }
    }
}

$ByHand = New-Object System.Collections.Generic.List[string]
function Add-ByHand($What, $Command) { $ByHand.Add("  - $What`n      $Command") }

foreach ($model in @(Get-CandidateModels | Sort-Object -Unique)) {
    if (Test-Recorded "model:$model") { continue }
    if ($Pulled -contains $model -or $Pulled -contains "${model}:latest") { Add-ByHand "Ollama model $model" "ollama rm $model" }
}
if (-not (Test-Recorded "ollama:app") -and (Test-Path -LiteralPath (Join-Path $OllamaHome "unins000.exe"))) {
    Add-ByHand "Ollama, if nothing else of yours uses it" "Settings > Apps > Installed apps > Ollama > Uninstall"
}
if (-not (Test-Recorded "node:local") -and (Test-Path -LiteralPath (Join-Path $NodeHome "node.exe"))) {
    Add-ByHand "Node in $NodeHome, and its entry in your user PATH" "Remove-Item -Recurse -Force `"$NodeHome`""
}
foreach ($name in $InstallerUserEnv) {
    $current = [Environment]::GetEnvironmentVariable($name, "User")
    if ($current -and @(Get-Recorded "env:$name=").Count -eq 0) {
        Add-ByHand "User variable $name=$current, if you did not set it yourself" "[Environment]::SetEnvironmentVariable(`"$name`", `$null, `"User`")"
    }
}
if (-not (Test-Recorded "uv") -and (Test-Cmd "uv")) {
    $uvExe = (Get-Command uv).Source
    Add-ByHand "uv's download cache" "& `"$uvExe`" cache clean"
    Add-ByHand "Pythons uv manages, if no other project uses them" "& `"$uvExe`" python uninstall --all"
}

function Show-ByHand {
    if ($ByHand.Count -eq 0) { return }
    Write-Host ""
    Write-Host "Not removed: no install record says this checkout added these. Check each,"
    Write-Host "and remove it by hand if Luminary installed it:"
    foreach ($line in $ByHand) { Write-Host $line }
}

# ---------------------------------------------------------------------------
# Confirm, then run.
# ---------------------------------------------------------------------------
if ($Steps.Count -eq 0) {
    Write-Info "Nothing to remove."
} else {
    Write-Host ""
    Write-Host "This will:"
    foreach ($s in $Steps) { Write-Host "  - $($s.Desc)" }
    Write-Host ""
}
if (-not $PurgeData -and (Test-Path -LiteralPath $Library)) {
    Write-Info "Keeping the dev library at $Library (pass -PurgeData to delete it)."
}

if ($Steps.Count -eq 0) { Show-ByHand; exit 0 }
if ($DryRun) {
    Write-Info "Dry run: nothing was removed."
    Show-ByHand
    exit 0
}
if (-not $Yes) {
    if ([Console]::IsInputRedirected) {
        Write-Host "[uninstall] Not a terminal; pass -Yes to confirm." -ForegroundColor Red
        exit 1
    }
    $answer = Read-Host "Proceed? [y/N]"
    if ($answer -notin @("y", "Y", "yes")) {
        Write-Info "Cancelled; nothing was removed."
        exit 0
    }
}

foreach ($s in $Steps) {
    Write-Info $s.Desc
    try { & $s.Action $s.Arg } catch { Write-Warn "  failed; continuing: $_" }
}
Write-Info "Done. Reinstall with: .\scripts\install.ps1"
Show-ByHand
