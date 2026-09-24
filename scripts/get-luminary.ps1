# get-luminary.ps1 -- install or remove the Luminary desktop app on Windows in one command.
#
#   irm https://raw.githubusercontent.com/nupsea/luminary/master/scripts/get-luminary.ps1 | iex
#
# Per-user install into %LOCALAPPDATA%: no administrator prompt. Downloads the
# release's setup .exe, verifies it against the release's .sha256, installs it
# silently and opens the app, whose first-run setup fetches the models.
#
# $env:LUMINARY_VERSION = "0.13.2"   a specific release instead of the latest
# $env:LUMINARY_INSTALLER = "<file>"  install a local setup .exe, no download
# $env:LUMINARY_NO_LAUNCH = "1"       install without opening the app
# $env:LUMINARY_INSTALL_ANYWAY = "1"  install on a host that cannot run local models, without asking
# $env:LUMINARY_UNINSTALL = "1"       remove the app, after listing what goes and asking; your library is kept
# $env:LUMINARY_ASSUME_YES = "1"      remove without asking, for scripts (the library is still kept)
# $env:LUMINARY_REUSE_MODELS = "1"    copy your own Ollama's models without asking ("0": never)
# $env:LUMINARY_ALLOW_DOWNGRADE = "1" install an older version over a newer one
#
# Errors never exit: under `irm | iex`, exit closes the user's window. A failure
# saves a report and, if the user agrees, opens it as an email to the developer.

# Checked before any .NET call, which constrained mode refuses with an unhelpful message.
if ($ExecutionContext.SessionState.LanguageMode -ne "FullLanguage") {
    throw "PowerShell is locked to $($ExecutionContext.SessionState.LanguageMode) mode on this computer, usually by an organization policy. Download the setup .exe from https://github.com/nupsea/luminary/releases and run it instead."
}

$LuminaryPreferences = @{ Error = $ErrorActionPreference; Progress = $ProgressPreference }
$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1 downloads an order of magnitude slower with the bar drawn.
$ProgressPreference = "SilentlyContinue"

$ReportAddress = "eanups@yahoo.com"
$LuminaryRepo = if ($env:LUMINARY_REPO) { $env:LUMINARY_REPO } else { "nupsea/luminary" }
$ReleasesPage = "https://github.com/$LuminaryRepo/releases"
$LibraryDir = Join-Path $env:LOCALAPPDATA "sh.luminary.app"
$LogsDir = Join-Path $env:LOCALAPPDATA "Luminary\Logs"
$ModelsDir = Join-Path $LibraryDir "ollama\models"
$AppExeName = "luminary-desktop.exe"
# The Ollama tags model_registry.REGISTRY measures, which are the ones worth reusing
# from a user's own Ollama. test_get_luminary_script.py fails when they drift.
$KnownModels = @("llama3.2", "qwen3.5:4b", "phi4-mini", "gemma3:4b", "qwen2.5vl:7b", "qwen2.5:14b-instruct")
# The 0.13.2 install unpacks to 1.62 GB beside a 0.30 GB download: 1.9 GB free fails
# partway, 2.5 GB leaves room for the installer's scratch copy.
$NeedFreeGB = 2.5
# CI's silent install takes 2 minutes; antivirus scanning each of its files on a slow
# disk can take ten times that.
$SetupTimeoutMinutes = 30

$LuminaryLog = New-Object System.Collections.Generic.List[string]
$LuminaryDeclined = $false

function Write-Step([string]$message) {
    Write-Host "==> $message"
    $LuminaryLog.Add("==> $message")
}

function Write-Warn([string]$message) {
    Write-Host "warning: $message" -ForegroundColor Yellow
    $LuminaryLog.Add("warning: $message")
}

# A refusal the user can act on: said plainly, with no failure report offered.
function Stop-Luminary([string]$message) {
    $script:LuminaryDeclined = $true
    throw $message
}

# CI runners can report an interactive session with nobody at the keyboard.
function Test-Interactive {
    if ($env:CI) { return $false }
    return ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected)
}

# The host checks and message are host_support.local_inference_support's, so a
# refused machine hears it before the download rather than after.
# test_get_luminary_script.py fails when they drift. The dash is a [char] because
# Windows PowerShell 5.1 reads a BOM-less script as ANSI.
$MinRamGB = 16
$UnsupportedMessage = "This system isn't supported for running local models at a usable speed. Reading, search, notes and your learner record all work as normal. For answers and flashcards, add your own API key in Settings $([char]0x2014) or wait for the hosted version of Luminary, which is coming soon."

function Test-Accelerator {
    $visible = "$env:CUDA_VISIBLE_DEVICES".Trim()
    if ($visible -and $visible -ne "-1") { return $true }
    $root = if ($env:SYSTEMROOT) { $env:SYSTEMROOT } else { "C:\Windows" }
    $system32 = Join-Path $root "System32"
    if (Test-Path (Join-Path $system32 "nvcuda.dll")) { return $true }
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { return $true }
    return (Test-Path (Join-Path $system32 "amdhip64.dll"))
}

# Rounded up (I-56); 0 when unreadable, which is not a refusal on its own.
function Get-RamGB {
    try { return [int][math]::Ceiling((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB) }
    catch { return 0 }
}

function Confirm-HostSupport {
    if ("$env:LUMINARY_HOST_SUPPORTED".Trim().ToLowerInvariant() -in @("1", "true", "yes")) { return }
    $why = $null
    if (-not (Test-Accelerator)) {
        $why = "no NVIDIA or AMD graphics card was found"
    } else {
        $ram = Get-RamGB
        if ($ram -gt 0 -and $ram -lt $MinRamGB) {
            $why = "this machine has $($ram)GB of memory; local models need $($MinRamGB)GB"
        }
    }
    if (-not $why) { return }
    Write-Host ""
    Write-Host $UnsupportedMessage -ForegroundColor Yellow
    Write-Host "($why)"
    Write-Host ""
    if ($env:LUMINARY_INSTALL_ANYWAY -eq "1") {
        Write-Step "Installing anyway for reading, search and notes"
        return
    }
    if (Test-Interactive) {
        $answer = Read-Host "Install anyway for reading, search and notes? [y/N]"
        if ($answer -match '^(y|yes)$') { return }
    }
    Stop-Luminary "Not installed. To install for reading, search and notes, set `$env:LUMINARY_INSTALL_ANYWAY = `"1`" and run this again."
}

function Assert-Environment {
    if ($PSVersionTable.PSVersion.Major -lt 5) {
        Stop-Luminary "This needs Windows PowerShell 5.1 or newer (this is $($PSVersionTable.PSVersion))."
    }
    if ([Environment]::OSVersion.Version.Major -lt 10) {
        Stop-Luminary "Luminary needs Windows 10 or 11 (this is $([Environment]::OSVersion.VersionString))."
    }
    if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64" -and $env:PROCESSOR_ARCHITEW6432 -ne "AMD64") {
        Stop-Luminary "Luminary is built for x64 Windows only (this is $env:PROCESSOR_ARCHITECTURE)."
    }
    foreach ($name in @("LOCALAPPDATA", "TEMP")) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if (-not $value -or -not (Test-Path -LiteralPath $value -PathType Container)) {
            Stop-Luminary "%$name% does not name an existing folder ('$value'). Windows sets it at sign-in: sign out and back in, then run this again."
        }
    }
}

function Initialize-Network {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    # A proxy that authenticates as the signed-in user, as most corporate ones do.
    try { [Net.WebRequest]::DefaultWebProxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials } catch { }
}

# One line a person can act on, from a failed web request.
function Get-WebFailure($err) {
    $ex = $err.Exception
    if ($ex.PSObject.Properties["Response"] -and $ex.Response) {
        $code = [int]$ex.Response.StatusCode
        if ($code -eq 404) { return "not found (HTTP 404)" }
        if ($code -eq 403 -or $code -eq 429) {
            return "GitHub refused the request (HTTP $code), usually its hourly limit for your network; try again in an hour"
        }
        return "HTTP $code"
    }
    while ($ex.InnerException) { $ex = $ex.InnerException }
    return $ex.Message
}

function Invoke-Download([string]$uri, [string]$outFile) {
    for ($attempt = 1; ; $attempt++) {
        try {
            Invoke-WebRequest -Uri $uri -OutFile $outFile -UseBasicParsing
            return
        } catch {
            $why = Get-WebFailure $_
            if ($attempt -ge 3 -or $why -like "*HTTP 4*") {
                throw "Could not download $([IO.Path]::GetFileName($outFile)): $why. Check your internet connection, or download it from $ReleasesPage."
            }
            Write-Warn "download interrupted ($why); retrying"
            Start-Sleep -Seconds (5 * $attempt)
        }
    }
}

function Get-Release {
    if ($env:LUMINARY_RELEASE_JSON) {
        return (Get-Content -LiteralPath $env:LUMINARY_RELEASE_JSON -Raw | ConvertFrom-Json)
    }
    $version = if ($env:LUMINARY_VERSION) { $env:LUMINARY_VERSION.Trim().TrimStart('v') } else { "latest" }
    $api = "https://api.github.com/repos/$LuminaryRepo/releases/latest"
    if ($version -ne "latest") { $api = "https://api.github.com/repos/$LuminaryRepo/releases/tags/v$version" }
    try {
        return (Invoke-RestMethod -Uri $api -Headers @{ Accept = "application/vnd.github+json" })
    } catch {
        $why = Get-WebFailure $_
        if ($why -like "*HTTP 404*" -and $version -ne "latest") {
            Stop-Luminary "There is no Luminary release v$version. The releases are listed at $ReleasesPage."
        }
        if ($why -like "*HTTP 403*" -or $why -like "*HTTP 429*") { Stop-Luminary "Could not read the release list: $why." }
        throw "Could not read the release list from GitHub: $why. Check your internet connection, or download the setup .exe from $ReleasesPage."
    }
}

function Get-ReleaseAsset($release, [string]$pattern) {
    $release.assets | Where-Object { $_.name -like $pattern } | Select-Object -First 1
}

# Bytes free on the drive holding $path; $null when unreadable (a network drive, say).
function Get-FreeBytes([string]$path) {
    try { return (New-Object IO.DriveInfo ([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($path)))).AvailableFreeSpace }
    catch { return $null }
}

function Assert-FreeSpace([long]$downloadBytes) {
    $free = Get-FreeBytes $env:LOCALAPPDATA
    if ($null -ne $free -and $free -lt $NeedFreeGB * 1GB) {
        Stop-Luminary ("Only {0:N1} GB is free on the drive holding {1}; installing Luminary needs {2} GB, and its models about 4 GB more on first launch. Free some space and run this again." -f ($free / 1GB), $env:LOCALAPPDATA, $NeedFreeGB)
    }
    $tempRoot = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($env:TEMP))
    if ($tempRoot -ne [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($env:LOCALAPPDATA))) {
        $free = Get-FreeBytes $env:TEMP
        if ($null -ne $free -and $free -lt $downloadBytes + 100MB) {
            Stop-Luminary ("Only {0:N1} GB is free on the drive holding %TEMP% ({1}); the download needs {2:N1} GB there." -f ($free / 1GB), $env:TEMP, (($downloadBytes + 100MB) / 1GB))
        }
    }
}

function Get-LuminaryEntry {
    Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -eq "Luminary" -and $_.InstallLocation } | Select-Object -First 1
}

function Get-MachineEntry {
    Get-ItemProperty "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -eq "Luminary" } | Select-Object -First 1
}

# The per-user install. A folder counts only while it holds the app or its uninstaller,
# so a folder of logs is not an install.
# A folder named for Luminary is its own; one chosen by hand may be shared with other
# software, so only Luminary's exact files are touched there.
function Test-OwnFolder([string]$dir) { return ($dir -and (Split-Path -Leaf $dir) -ieq "Luminary") }

function Find-LuminaryInstall {
    $entry = Get-LuminaryEntry
    if ($entry) {
        $dir = $entry.InstallLocation.Trim('"').TrimEnd('\')
        if ((Test-Path -LiteralPath (Join-Path $dir $AppExeName)) -or (Test-Path -LiteralPath (Join-Path $dir "uninstall.exe"))) {
            return $dir
        }
    }
    foreach ($dir in @("$env:LOCALAPPDATA\Luminary", "$env:LOCALAPPDATA\Programs\Luminary")) {
        if (Test-Path -LiteralPath (Join-Path $dir $AppExeName)) { return $dir }
    }
    return $null
}

function Test-Under([string]$path, [string]$root) {
    if (-not $path -or -not $root) { return $false }
    return $path.StartsWith($root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NotRunning([string]$dir) {
    if (-not $dir) { return }
    $app = Join-Path $dir $AppExeName
    if (@(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -ieq $app }).Count -gt 0) {
        Stop-Luminary "Luminary is running. Close it, then run this again; your library is kept."
    }
}

# Refuses while the app's window is open, and stops the backend and engine a crash left
# behind. Matched by exact executable path, never by name: a user's own `ollama serve`,
# or anything else installed beside Luminary, survives.
function Stop-LeftoverProcesses([string]$dir) {
    Assert-NotRunning $dir
    $helpers = @((Join-Path $LibraryDir "engine"), (Join-Path $LibraryDir "engine.new"))
    if (Test-OwnFolder $dir) { $helpers += @((Join-Path $dir "python"), (Join-Path $dir "ollama")) }
    $procs = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path })
    $ours = @($procs | Where-Object { $p = $_.Path; @($helpers | Where-Object { Test-Under $p $_ }).Count -gt 0 })
    if ($ours.Count -eq 0) { return }
    Write-Step "Stopping Luminary's background processes left from an earlier run"
    $ours | Stop-Process -Force -ErrorAction SilentlyContinue
    $ours | ForEach-Object { try { $null = $_.WaitForExit(10000) } catch { } }
}

# An older app does not know a newer one's migrations, so it may not open the library.
function Confirm-Version([string]$new) {
    $entry = Get-LuminaryEntry
    if (-not $entry -or -not (Find-LuminaryInstall)) { return }
    $old = $null; $next = $null
    if (-not [version]::TryParse(("$($entry.DisplayVersion)" -replace '[-+].*$', ''), [ref]$old)) { return }
    if (-not [version]::TryParse(($new -replace '^v', '' -replace '[-+].*$', ''), [ref]$next)) { return }
    if ($next -eq $old) {
        Write-Step "Luminary $old is already installed; installing it again"
    } elseif ($next -gt $old) {
        Write-Step "Upgrading Luminary $old to $next"
    } elseif ($env:LUMINARY_ALLOW_DOWNGRADE -eq "1") {
        Write-Warn "replacing Luminary $old with the older $next"
    } else {
        Stop-Luminary "Luminary $old is installed and $next is older. An older version may not open a library that a newer one has upgraded. To install it anyway, set `$env:LUMINARY_ALLOW_DOWNGRADE = `"1`" and run this again."
    }
}

# A user's own Ollama is named, never touched: Luminary's runs on a private port with
# its own models folder, so the two share only the graphics card's memory.
function Get-UserOllama {
    $exe = $null
    $cmd = Get-Command ollama -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { $exe = $cmd.Source }
    elseif (Test-Path -LiteralPath "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe") { $exe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
    $ours = @((Join-Path $LibraryDir "engine"), (Join-Path $LibraryDir "engine.new"))
    $dir = Find-LuminaryInstall
    if ($dir) { $ours += Join-Path $dir "ollama" }  # only ever excluded, never stopped
    $running = @(Get-Process -Name "ollama", "ollama app" -ErrorAction SilentlyContinue | Where-Object {
        $p = $_.Path
        -not ($p -and @($ours | Where-Object { Test-Under $p $_ }).Count -gt 0)
    })
    return [pscustomobject]@{ Exe = $exe; Running = ($running.Count -gt 0) }
}

function Get-OllamaStores {
    $own = [IO.Path]::GetFullPath($ModelsDir).TrimEnd('\')
    $seen = @{}
    foreach ($candidate in @($env:OLLAMA_MODELS,
            [Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User"),
            [Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "Machine"),
            (Join-Path $env:USERPROFILE ".ollama\models"))) {
        if (-not $candidate) { continue }
        try { $full = [IO.Path]::GetFullPath($candidate).TrimEnd('\') } catch { continue }
        if ($seen.ContainsKey($full) -or $full -ieq $own) { continue }
        $seen[$full] = $true
        if ((Test-Path -LiteralPath (Join-Path $full "manifests")) -and (Test-Path -LiteralPath (Join-Path $full "blobs"))) { $full }
    }
}

function Get-ManifestPath([string]$store, [string]$model) {
    $name, $tag = $model -split ':', 2
    if (-not $tag) { $tag = "latest" }
    return (Join-Path $store "manifests\registry.ollama.ai\library\$name\$tag")
}

# Model $model in $store, with every blob its manifest names; $null unless all are there.
function Get-StoredModel([string]$store, [string]$model) {
    $manifest = Get-ManifestPath $store $model
    if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { return $null }
    try { $m = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json } catch { return $null }
    $digests = @(@($m.config) + @($m.layers) | ForEach-Object { "$($_.digest)" } |
        Where-Object { $_ -match '^sha256:[0-9a-f]{64}$' } | ForEach-Object { $_.Substring(7) } | Select-Object -Unique)
    if ($digests.Count -eq 0) { return $null }
    $blobs = foreach ($d in $digests) {
        $file = Join-Path $store "blobs\sha256-$d"
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { return $null }
        [pscustomobject]@{ Digest = $d; Path = $file; Bytes = (Get-Item -LiteralPath $file).Length }
    }
    return [pscustomobject]@{
        Model = $model; Store = $store; Manifest = $manifest; Blobs = @($blobs)
        Bytes = (@($blobs) | Measure-Object -Property Bytes -Sum).Sum
    }
}

# Copied, never linked: a hard link would stop the user's Ollama deleting its own file
# while Luminary has the model open. Each blob is checked against its digest before the
# manifest makes the model visible.
function Copy-StoredModel($found) {
    $blobDir = Join-Path $ModelsDir "blobs"
    $manifest = Get-ManifestPath $ModelsDir $found.Model
    $added = New-Object System.Collections.Generic.List[string]
    $partial = $null
    Write-Step "Copying $($found.Model) from $($found.Store)"
    try {
        New-Item -ItemType Directory -Force -Path $blobDir, (Split-Path $manifest) | Out-Null
        foreach ($blob in $found.Blobs) {
            $dst = Join-Path $blobDir "sha256-$($blob.Digest)"
            if (Test-Path -LiteralPath $dst) { continue }
            $partial = "$dst.partial"
            [IO.File]::Copy($blob.Path, $partial, $true)
            if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $blob.Digest) {
                throw "it does not match its checksum in your Ollama"
            }
            Move-Item -LiteralPath $partial -Destination $dst -Force
            $added.Add($dst)
        }
        $partial = "$manifest.partial"
        Copy-Item -LiteralPath $found.Manifest -Destination $partial -Force
        Move-Item -LiteralPath $partial -Destination $manifest -Force
    } catch {
        # Only this run's copies go.
        foreach ($file in @($added) + @($partial)) {
            if ($file) { Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue }
        }
        Write-Warn "$($found.Model) was not copied: $($_.Exception.Message). Luminary downloads its own copy instead"
    }
}

function Invoke-ModelReuse {
    if ($env:LUMINARY_REUSE_MODELS -eq "0") { return }
    $stores = @(Get-OllamaStores)
    if ($stores.Count -eq 0) { return }
    $found = @(foreach ($model in $KnownModels) {
        if (Test-Path -LiteralPath (Get-ManifestPath $ModelsDir $model)) { continue }
        foreach ($store in $stores) {
            $stored = Get-StoredModel $store $model
            if ($stored) { $stored; break }
        }
    })
    if ($found.Count -eq 0) { return }
    Write-Step "Your Ollama already has models Luminary uses:"
    $found | ForEach-Object { Write-Host ("      {0} ({1:N0} MB)" -f $_.Model, ($_.Bytes / 1MB)) }
    $total = ($found | Measure-Object -Property Bytes -Sum).Sum
    $free = Get-FreeBytes $env:LOCALAPPDATA
    if ($null -ne $free -and $free -lt $total + 2GB) {
        Write-Warn ("copying them needs {0:N1} GB and {1:N1} GB is free; Luminary downloads what it needs instead" -f ($total / 1GB), ($free / 1GB))
        return
    }
    if ($env:LUMINARY_REUSE_MODELS -ne "1") {
        if (-not (Test-Interactive)) {
            Write-Step "To copy them rather than download them again, set `$env:LUMINARY_REUSE_MODELS = `"1`" and run this again."
            return
        }
        $answer = Read-Host ("Copy them ({0:N1} GB) rather than download them again? Your Ollama and its models are not changed. [Y/n]" -f ($total / 1GB))
        if ($answer -match '^(n|no)$') {
            Write-Step "Not copied; Luminary downloads its own."
            return
        }
    }
    foreach ($stored in $found) { Copy-StoredModel $stored }
}

function Show-UserOllama {
    $ollama = Get-UserOllama
    if (-not $ollama.Exe -and -not $ollama.Running -and @(Get-OllamaStores).Count -eq 0) { return }
    $where = if ($ollama.Exe) { " at $($ollama.Exe)" } else { "" }
    Write-Step "Found your own Ollama$where. Luminary runs its own copy, on a private port with its own models folder, and leaves yours as it is."
    if ($ollama.Running) {
        Write-Warn "your Ollama is running. While both hold a model they share the graphics card's memory and both slow down; if answers are slow, quit yours while you use Luminary."
    }
    Invoke-ModelReuse
}

function Get-WebView2Version {
    $id = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    foreach ($key in @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$id",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$id",
        "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$id"
    )) {
        $pv = (Get-ItemProperty -Path $key -Name pv -ErrorAction SilentlyContinue).pv
        if ($pv -and $pv -ne "0.0.0.0") { return $pv }
    }
    return $null
}

# Runs an NSIS installer or uninstaller silently and turns its exit code into a sentence.
function Invoke-Nsis([string]$exe, [string]$arguments, [string]$what) {
    try {
        $proc = Start-Process -FilePath $exe -ArgumentList $arguments -PassThru
    } catch {
        throw "Windows would not start the $what ($($_.Exception.Message)). Antivirus software or an application-control policy may be blocking it."
    }
    # Windows PowerShell 5.1 loses the exit code unless the handle is opened before exit.
    $null = $proc.Handle
    if (-not $proc.WaitForExit($SetupTimeoutMinutes * 60000)) {
        throw "The $what was still running after $SetupTimeoutMinutes minutes and was left running. Check Task Manager for it, then run this again."
    }
    switch ($proc.ExitCode) {
        0 { return }
        1 { throw "The $what was cancelled (exit code 1)." }
        2 { throw "The $what stopped before finishing (exit code 2). Usually Luminary was still running, or antivirus software held one of its files; close Luminary and run this again." }
        default { throw "The $what exited with code $($proc.ExitCode)." }
    }
}

function Install-Luminary {
    $existing = Find-LuminaryInstall
    if ($existing) { Stop-LeftoverProcesses $existing }

    Confirm-HostSupport
    if (Test-Path -LiteralPath $LibraryDir) {
        Write-Step "Found your library at $LibraryDir ($(Get-SizeText $LibraryDir)); it is kept and this version opens it."
    }

    $work = Join-Path $env:TEMP ("luminary-setup-" + [guid]::NewGuid().ToString("N"))
    try {
        New-Item -ItemType Directory -Path $work -Force | Out-Null
    } catch {
        throw "Could not create a folder in %TEMP% ($env:TEMP): $($_.Exception.Message)"
    }
    try {
        if ($env:LUMINARY_INSTALLER) {
            if (-not (Test-Path -LiteralPath $env:LUMINARY_INSTALLER)) { Stop-Luminary "No such file: $env:LUMINARY_INSTALLER" }
            $setup = (Resolve-Path -LiteralPath $env:LUMINARY_INSTALLER).Path
            if ([IO.Path]::GetFileName($setup) -match '^Luminary_(\d+(\.\d+)+)_') { Confirm-Version $Matches[1] }
            Assert-FreeSpace 0
        } else {
            $release = Get-Release
            Confirm-Version "$($release.tag_name)"
            $asset = Get-ReleaseAsset $release "Luminary_*_x64-setup.exe"
            if (-not $asset) { Stop-Luminary "Release $($release.tag_name) has no Windows installer; it may predate one." }
            $sum = Get-ReleaseAsset $release "$($asset.name).sha256"
            if (-not $sum) { throw "Release $($release.tag_name) has no checksum for $($asset.name); refusing to install unverified." }
            Assert-FreeSpace ([long]$asset.size)

            $setup = Join-Path $work $asset.name
            Write-Step "Downloading $($asset.name) ($([math]::Round($asset.size / 1MB)) MB)"
            Invoke-Download $asset.browser_download_url $setup
            Invoke-Download $sum.browser_download_url "$setup.sha256"
            if (-not (Test-Path -LiteralPath $setup)) {
                throw "The downloaded installer disappeared from $work. Antivirus software may have quarantined it; check its history, then run this again."
            }
            $size = (Get-Item -LiteralPath $setup).Length
            if ($asset.size -and $size -ne $asset.size) {
                throw "The download of $($asset.name) is incomplete ($size of $($asset.size) bytes). Run this again."
            }
            $expected = ((Get-Content -LiteralPath "$setup.sha256" -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
            $actual = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($expected -ne $actual) {
                throw "Checksum mismatch for $($asset.name) (expected $expected, got $actual). The download was corrupted or altered, and nothing was installed. Run this again; if it repeats, something on your network is changing downloads."
            }
        }

        Write-Step "Installing for $env:USERNAME (no administrator rights needed)"
        Invoke-Nsis $setup "/S" "installer"
    } finally {
        Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
    }

    $dir = Find-LuminaryInstall
    if (-not $dir) { throw "The installer finished but Luminary's install folder was not found." }
    $exe = Join-Path $dir $AppExeName
    if (-not (Test-Path -LiteralPath $exe)) { throw "The installer finished but $exe is missing." }
    $version = "$((Get-LuminaryEntry).DisplayVersion)"
    Write-Step "Luminary $(if ($version) { "$version " })is installed in $dir"
    Write-Host "    Your library lives in $($LibraryDir): your documents, notes, flashcards,"
    Write-Host "    reviews, settings and downloaded models. Removing the app keeps it."
    Write-Host "    To remove the app: Settings > Apps > Installed apps > Luminary > Uninstall,"
    Write-Host "    or run this command again with `$env:LUMINARY_UNINSTALL = `"1`"."
    if (-not (Get-WebView2Version)) {
        Write-Warn "Microsoft Edge WebView2, which draws Luminary's window, was not found. If Luminary opens no window, install it from https://go.microsoft.com/fwlink/p/?LinkId=2124703 and open Luminary again."
    }

    # Optional, so nothing in it may fail the install.
    try { Show-UserOllama } catch { Write-Warn "could not check for your own Ollama ($($_.Exception.Message))" }

    if ($env:LUMINARY_NO_LAUNCH -ne "1") {
        Write-Step "Opening Luminary. First launch downloads its models and takes a few minutes."
        try {
            Start-Process -FilePath $exe
        } catch {
            throw "Luminary is installed, but Windows would not open it ($($_.Exception.Message)). Open it from the Start menu."
        }
    }
}

# Deletes a folder Luminary rebuilds or left in %TEMP%: never a root, never outside
# %LOCALAPPDATA% or %TEMP%, and a link as a link. Nothing a user made is passed here.
# Returns $false when something could not be removed.
function Remove-OwnedItem([string]$path) {
    if (-not $path -or -not (Test-Path -LiteralPath $path)) { return $true }
    $full = [IO.Path]::GetFullPath($path).TrimEnd('\')
    if (-not ((Test-Under $full $env:LOCALAPPDATA) -or (Test-Under $full $env:TEMP))) {
        throw "Refusing to delete $full, which is outside %LOCALAPPDATA% and %TEMP%."
    }
    # A second try: antivirus often holds a file it is scanning for a moment.
    for ($attempt = 1; ; $attempt++) {
        try {
            $item = Get-Item -LiteralPath $full -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                $item.Delete()
            } elseif ($item.PSIsContainer) {
                [IO.Directory]::Delete($full, $true)
            } else {
                [IO.File]::Delete($full)
            }
            return $true
        } catch {
            if ($attempt -ge 2) {
                Write-Warn "could not remove $full ($($_.Exception.Message))"
                return $false
            }
            Start-Sleep -Seconds 3
        }
    }
}

function Get-SizeText([string]$path) {
    try {
        $bytes = (Get-ChildItem -LiteralPath $path -Recurse -Force -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
        return ("{0:N1} GB" -f ($bytes / 1GB))
    } catch {
        return "size unknown"
    }
}

# What an interrupted install or a missing uninstaller leaves behind: shortcuts and an
# Apps entry pointing at a folder that is gone.
function Remove-StaleEntries {
    $installs = @("$env:LOCALAPPDATA\Luminary", "$env:LOCALAPPDATA\Programs\Luminary")
    try {
        $shell = New-Object -ComObject WScript.Shell
        foreach ($lnk in @(
            (Join-Path ([Environment]::GetFolderPath("Programs")) "Luminary.lnk"),
            (Join-Path ([Environment]::GetFolderPath("Desktop")) "Luminary.lnk")
        )) {
            if (-not (Test-Path -LiteralPath $lnk)) { continue }
            $target = $shell.CreateShortcut($lnk).TargetPath
            if (($installs | Where-Object { Test-Under $target $_ }) -and -not (Test-Path -LiteralPath $target)) {
                Remove-Item -LiteralPath $lnk -Force
            }
        }
    } catch {
        Write-Warn "could not check Luminary's shortcuts ($($_.Exception.Message))"
    }
    Get-ChildItem "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall" -ErrorAction SilentlyContinue |
        Where-Object {
            $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
            $p.DisplayName -eq "Luminary" -and -not ($p.InstallLocation -and (Test-Path -LiteralPath $p.InstallLocation.Trim('"')))
        } | Remove-Item -Recurse -Force
}

function Format-Quoted([string]$path) { return "'" + ($path -replace "'", "''") + "'" }

# Deletes empty folders under $path, bottom up, without entering a link.
function Remove-EmptyFolders([string]$path) {
    $item = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    if (-not $item -or -not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { return }
    foreach ($child in @(Get-ChildItem -LiteralPath $path -Directory -Force -ErrorAction SilentlyContinue)) {
        Remove-EmptyFolders $child.FullName
    }
    if (-not (Get-ChildItem -LiteralPath $path -Force -ErrorAction SilentlyContinue)) {
        try { [IO.Directory]::Delete($path, $false) } catch { }
    }
}

# Removes the named files from $dir, then whatever folders that left empty. Anything
# else stays, and Show-Kept lists it for the user.
function Remove-FilesThenFolders([string]$dir, [string[]]$names) {
    if (-not $dir -or -not (Test-Path -LiteralPath $dir -PathType Container)) { return }
    foreach ($name in $names) {
        $file = Join-Path $dir $name
        if (Test-Path -LiteralPath $file -PathType Leaf) {
            try { Remove-Item -LiteralPath $file -Force } catch { Write-Warn "could not remove $file ($($_.Exception.Message))" }
        }
    }
    Remove-EmptyFolders $dir
}

function Show-Kept([string[]]$candidates) {
    $left = @($candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Sort-Object -Unique)
    $left = @($left | Where-Object { $p = $_; -not ($left | Where-Object { Test-Under $p $_ }) })
    if ($left.Count -gt 0) {
        Write-Host ""
        Write-Host "These folders still hold files Luminary did not put there, so they were left alone:"
        foreach ($p in $left) {
            Write-Host "  $p"
            Write-Host "    look:   Get-ChildItem -LiteralPath $(Format-Quoted $p) -Recurse -Force"
            Write-Host "    delete: Remove-Item -LiteralPath $(Format-Quoted $p) -Recurse -Force"
        }
    }
    if (-not (Test-Path -LiteralPath $LibraryDir)) { return }
    Write-Host ""
    Write-Host "Your library was kept at $LibraryDir ($(Get-SizeText $LibraryDir))."
    Write-Host "It holds every document, note, flashcard and review you have created, your settings"
    Write-Host "(including any API keys) and the downloaded models. Reinstalling picks it up again."
    $item = Get-Item -LiteralPath $LibraryDir -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        Write-Host "It is a link to $($item.Target); that folder is the one holding the data."
    }
    Write-Host "To free only the models:   Remove-Item -LiteralPath $(Format-Quoted $ModelsDir) -Recurse -Force"
    Write-Host "To delete it permanently:  Remove-Item -LiteralPath $(Format-Quoted $LibraryDir) -Recurse -Force"
}

# What an uninstall would remove, as lines for the user; empty when nothing is installed.
function Get-UninstallItems([string]$dir) {
    if ($dir) { "the app in $dir, its Start menu and desktop shortcuts, and its entry in Settings > Apps" }
    if (Test-Path -LiteralPath (Join-Path $LogsDir "luminary.log")) { "Luminary's log files in $LogsDir" }
    if ((Test-Path -LiteralPath (Join-Path $LibraryDir "engine")) -or (Test-Path -LiteralPath (Join-Path $LibraryDir "engine.new"))) {
        "the copy of its engine in $(Join-Path $LibraryDir "engine"), which it rebuilds when reinstalled"
    }
}

# Lists what goes and what stays, then asks; $false when the user says no.
function Confirm-Uninstall([string[]]$items) {
    Write-Host ""
    Write-Host "This removes:"
    $items | ForEach-Object { Write-Host "  - $_" }
    if (Test-Path -LiteralPath $LibraryDir) {
        Write-Host ""
        Write-Host "It does not touch your library at $LibraryDir ($(Get-SizeText $LibraryDir)):"
        Write-Host "your documents, notes, flashcards, reviews, settings (including API keys)"
        Write-Host "and downloaded models all stay, and reinstalling picks them up again."
    }
    Write-Host ""
    if ($env:LUMINARY_ASSUME_YES -eq "1") { return $true }
    if (-not (Test-Interactive)) {
        Stop-Luminary "Nothing was removed: there is no one here to confirm. To remove Luminary without asking, set `$env:LUMINARY_ASSUME_YES = `"1`" and run this again."
    }
    return ((Read-Host "Remove Luminary? [y/N]") -match '^(y|yes)$')
}

function Uninstall-Luminary {
    $dir = Find-LuminaryInstall
    if (-not $dir) {
        $machine = Get-MachineEntry
        if ($machine) {
            Stop-Luminary "Luminary is installed for all users ($($machine.InstallLocation)), which this does not remove. Remove it from Settings > Apps > Installed apps, as an administrator."
        }
    }
    Assert-NotRunning $dir
    $items = @(Get-UninstallItems $dir)
    if ($items.Count -eq 0) {
        Remove-StaleEntries
        Write-Step "Luminary is not installed here."
        Show-Kept @()
        return
    }
    if (-not (Confirm-Uninstall $items)) {
        Write-Step "Nothing was removed."
        return
    }
    Stop-LeftoverProcesses $dir
    if ($dir) {
        Write-Step "Removing Luminary from $dir"
        $uninstaller = Join-Path $dir "uninstall.exe"
        if (Test-Path -LiteralPath $uninstaller) {
            # `_?=` runs it in place and waits; otherwise it relaunches from %TEMP% and
            # returns at once. Unquoted and last: NSIS takes the rest of the line.
            Invoke-Nsis $uninstaller "/S _?=$dir" "uninstaller"
        }
    }
    Remove-StaleEntries
    # The relocated engine is the app's own copy, rebuilt on its next launch.
    foreach ($copy in @("engine", "engine.new")) { $null = Remove-OwnedItem (Join-Path $LibraryDir $copy) }
    $logs = @(Get-ChildItem -LiteralPath $LogsDir -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^luminary\.log(\.\d+)?$' } | ForEach-Object { $_.Name })
    Remove-FilesThenFolders $LogsDir $logs
    $shared = Join-Path $env:LOCALAPPDATA "Luminary"
    Remove-FilesThenFolders $shared @()
    # With `_?=` the uninstaller cannot delete itself.
    if (Test-OwnFolder $dir) {
        Remove-FilesThenFolders $dir @("uninstall.exe")
    } elseif ($dir) {
        Remove-Item -LiteralPath (Join-Path $dir "uninstall.exe") -Force -ErrorAction SilentlyContinue
    }
    Get-ChildItem -LiteralPath $env:TEMP -Directory -Filter "luminary-setup-*" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^luminary-setup-[0-9a-f]{32}$' } |
        ForEach-Object { $null = Remove-OwnedItem $_.FullName }
    Write-Step "Luminary is removed."
    # A hand-picked folder may be shared, so it is never offered for deletion.
    $own = if (Test-OwnFolder $dir) { $dir } else { $null }
    Show-Kept @($own, $LogsDir, $shared)
}

function Get-FailureReport($err, [string]$action) {
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("Luminary $action failed")
    $lines.Add("When: " + (Get-Date).ToUniversalTime().ToString("u"))
    $lines.Add("Error: " + $err.Exception.Message)
    if ($err.InvocationInfo -and $err.InvocationInfo.Line) {
        $lines.Add("At: line $($err.InvocationInfo.ScriptLineNumber): $($err.InvocationInfo.Line.Trim())")
    }
    $lines.Add("Requested: version " + $(if ($env:LUMINARY_VERSION) { $env:LUMINARY_VERSION } else { "latest" }))
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $lines.Add("Windows: $($os.Caption) $($os.Version)")
    } catch { $lines.Add("Windows: " + [Environment]::OSVersion.VersionString) }
    $lines.Add("PowerShell: $($PSVersionTable.PSVersion)")
    $lines.Add("Architecture: $env:PROCESSOR_ARCHITECTURE")
    $lines.Add("Memory: $(Get-RamGB) GB")
    try {
        Get-CimInstance Win32_VideoController | ForEach-Object { $lines.Add("Graphics: $($_.Name) (driver $($_.DriverVersion))") }
    } catch { $lines.Add("Graphics: unreadable") }
    $free = Get-FreeBytes $env:LOCALAPPDATA
    if ($null -ne $free) { $lines.Add("Free space: {0:N1} GB" -f ($free / 1GB)) }
    $webview = Get-WebView2Version
    $lines.Add("WebView2: " + $(if ($webview) { $webview } else { "not found" }))
    $installed = Find-LuminaryInstall
    $lines.Add("Installed at: " + $(if ($installed) { $installed } else { "not installed" }))
    $lines.Add("")
    $lines.Add("Steps:")
    $LuminaryLog | ForEach-Object { $lines.Add($_) }
    $text = $lines -join "`r`n"
    if ($env:USERPROFILE) { $text = $text -replace [regex]::Escape($env:USERPROFILE), "%USERPROFILE%" }
    # Shorter names would redact ordinary words along with them.
    foreach ($name in @($env:COMPUTERNAME, $env:USERNAME)) {
        if ($name -and $name.Length -ge 3) { $text = $text -replace [regex]::Escape($name), "<redacted>" }
    }
    return $text
}

function Send-FailureReport($err, [string]$action) {
    $text = Get-FailureReport $err $action
    $path = $null
    foreach ($dir in @([Environment]::GetFolderPath("Desktop"), $env:USERPROFILE, $env:TEMP)) {
        if (-not $dir -or -not (Test-Path -LiteralPath $dir)) { continue }
        try {
            $path = Join-Path $dir "luminary-$action-report.txt"
            [IO.File]::WriteAllText($path, $text)
            break
        } catch { $path = $null }
    }
    Write-Host ""
    if ($path) { Write-Host "A report of what went wrong was saved to:`n  $path" }
    if (-not (Test-Interactive)) {
        if ($path) { Write-Host "To get help, email it to $ReportAddress." }
        return
    }
    Write-Host "It lists your Windows version, graphics card, memory, free disk space and the steps above;"
    Write-Host "no documents or files of yours, and your user and computer names are removed."
    $answer = Read-Host "Email it to the Luminary developer at $($ReportAddress)? Your mail app opens with the report filled in, and nothing is sent until you press Send. [y/N]"
    if ($answer -notmatch '^(y|yes)$') {
        Write-Host "Not sent."
        return
    }
    $copied = $false
    try { Set-Clipboard -Value $text; $copied = $true } catch { }
    $subject = "Luminary $action failed: " + $err.Exception.Message
    if ($subject.Length -gt 120) { $subject = $subject.Substring(0, 120) }
    # Windows refuses a mailto: link much past 2,000 characters; the full text is on
    # the clipboard and in the saved file.
    $body = $text
    while ($body.Length -gt 200 -and [uri]::EscapeDataString($body).Length -gt 1500) {
        $body = $body.Substring(0, [int]($body.Length * 0.8))
    }
    if ($body.Length -lt $text.Length) { $body += "`r`n[...] The full report is attached or pasted below." }
    try {
        Start-Process ("mailto:$ReportAddress" + "?subject=" + [uri]::EscapeDataString($subject) + "&body=" + [uri]::EscapeDataString($body))
        Write-Host "Your mail app should now show the email; press Send there."
    } catch {
        Write-Host "No mail app is set up on this computer."
    }
    if ($copied) { Write-Host "The full report is on your clipboard: with webmail, paste it into a new email to $ReportAddress." }
    if ($path) {
        Write-Host "Or attach the file: $path"
        try { Start-Process explorer.exe "/select,`"$path`"" } catch { }
    }
}

$LuminaryAction = if ($env:LUMINARY_UNINSTALL -eq "1") { "uninstall" } else { "install" }
try {
    Assert-Environment
    Initialize-Network
    if ($LuminaryAction -eq "uninstall") { Uninstall-Luminary } else { Install-Luminary }
} catch {
    $failure = $_
    Write-Host ""
    Write-Host "error: $($failure.Exception.Message)" -ForegroundColor Red
    $LuminaryLog.Add("error: $($failure.Exception.Message)")
    if (-not $LuminaryDeclined) {
        try { Send-FailureReport $failure $LuminaryAction } catch { Write-Host "(The failure report could not be written: $($_.Exception.Message))" }
    }
    # A script or CI step needs the failure; a person at the prompt has just read it.
    if (-not (Test-Interactive)) { throw $failure.Exception.Message }
} finally {
    $ErrorActionPreference = $LuminaryPreferences.Error
    $ProgressPreference = $LuminaryPreferences.Progress
}
