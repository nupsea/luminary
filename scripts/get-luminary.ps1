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
# $env:LUMINARY_UNINSTALL = "1"       remove the app; the library is kept unless you type DELETE
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

function Find-LuminaryInstall {
    $keys = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($key in $keys) {
        $entry = Get-ItemProperty $key -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -eq "Luminary" } | Select-Object -First 1
        if ($entry -and $entry.InstallLocation) {
            $dir = $entry.InstallLocation.Trim('"').TrimEnd('\')
            if (Test-Path -LiteralPath $dir) { return $dir }
        }
    }
    # A folder holding only the logs is not an install.
    foreach ($dir in @("$env:LOCALAPPDATA\Luminary", "$env:LOCALAPPDATA\Programs\Luminary")) {
        if (Test-Path (Join-Path $dir "*.exe")) { return $dir }
    }
    return $null
}

function Find-LuminaryExe([string]$dir) {
    Get-ChildItem -Path $dir -Filter "*.exe" -File |
        Where-Object { $_.Name -notlike "uninstall*" } | Select-Object -First 1
}

function Test-Under([string]$path, [string]$root) {
    if (-not $path -or -not $root) { return $false }
    return $path.StartsWith($root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)
}

# Refuses while the app's window is open, and stops the backend and engine a crash left
# behind. Matched by executable path, never by name: a user's own `ollama serve` survives.
function Stop-LeftoverProcesses([string]$dir) {
    $engine = Join-Path $LibraryDir "engine"
    $ours = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and ((Test-Under $_.Path $dir) -or (Test-Under $_.Path $engine))
    })
    $app = @($ours | Where-Object { $dir -and [IO.Path]::GetDirectoryName($_.Path) -ieq $dir })
    if ($app.Count -gt 0) {
        Stop-Luminary "Luminary is running. Close it, then run this again; your library is kept."
    }
    if ($ours.Count -eq 0) { return }
    Write-Step "Stopping Luminary's background processes left from an earlier run"
    $ours | Stop-Process -Force -ErrorAction SilentlyContinue
    $ours | ForEach-Object { try { $null = $_.WaitForExit(10000) } catch { } }
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
            Assert-FreeSpace 0
        } else {
            $release = Get-Release
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
    $exe = Find-LuminaryExe $dir
    if (-not $exe) { throw "No Luminary executable in $dir." }
    Write-Step "Installed to $dir. To remove it, run this again with `$env:LUMINARY_UNINSTALL = `"1`"; your library is kept."
    if (-not (Get-WebView2Version)) {
        Write-Warn "Microsoft Edge WebView2, which draws Luminary's window, was not found. If Luminary opens no window, install it from https://go.microsoft.com/fwlink/p/?LinkId=2124703 and open Luminary again."
    }

    if ($env:LUMINARY_NO_LAUNCH -ne "1") {
        Write-Step "Opening Luminary. First launch downloads its models and takes a few minutes."
        try {
            Start-Process -FilePath $exe.FullName
        } catch {
            throw "Luminary is installed, but Windows would not open it ($($_.Exception.Message)). Open it from the Start menu."
        }
    }
}

# Deletes only what Luminary owns: a path under %LOCALAPPDATA% or %TEMP%, never a root,
# and a link as a link. Returns $false when something could not be removed.
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

function Confirm-LibraryRemoval {
    if (-not (Test-Path -LiteralPath $LibraryDir)) { return }
    Write-Host ""
    Write-Host "Your library is still at $LibraryDir ($(Get-SizeText $LibraryDir))."
    Write-Host "It holds every document, note, flashcard and review you have created, your settings"
    Write-Host "(including any API keys) and the downloaded models."
    if ((Get-Item -LiteralPath $LibraryDir -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        Write-Step "It is a link to another folder, so it was kept. Delete that folder yourself if you no longer want it."
        return
    }
    if (-not (Test-Interactive)) {
        Write-Step "Not running interactively: library kept. Delete the folder above yourself if you no longer want it."
        return
    }
    $answer = Read-Host "Delete it permanently? Type DELETE to confirm, anything else keeps it"
    if ($answer -ceq "DELETE") {
        if (Remove-OwnedItem $LibraryDir) { Write-Step "Library deleted." }
        return
    }
    Write-Step "Library kept."
    $models = Join-Path $LibraryDir "ollama\models"
    if (-not (Test-Path -LiteralPath $models)) { return }
    $answer = Read-Host "Remove just the downloaded models ($(Get-SizeText $models)) to free space? They download again if you reinstall. [y/N]"
    if ($answer -match '^(y|yes)$') {
        if (Remove-OwnedItem $models) { Write-Step "Models removed." }
    }
}

function Uninstall-Luminary {
    $dir = Find-LuminaryInstall
    Stop-LeftoverProcesses $dir
    if ($dir) {
        Write-Step "Removing Luminary from $dir"
        $uninstaller = Join-Path $dir "uninstall.exe"
        if (Test-Path -LiteralPath $uninstaller) {
            # `_?=` runs it in place and waits; otherwise it relaunches from %TEMP% and
            # returns at once. Unquoted and last: NSIS takes the rest of the line.
            Invoke-Nsis $uninstaller "/S _?=$dir" "uninstaller"
        }
        # The uninstaller removes only the files it installed: not itself, the logs, or
        # anything written at runtime.
        if (-not (Remove-OwnedItem $dir)) {
            throw "Some files in $dir are in use. Restart Windows, then run this again."
        }
    } else {
        Write-Step "Luminary's app is not installed; cleaning up what an earlier install left."
    }
    Remove-StaleEntries
    # The app rebuilds these on its next launch, so they are never part of the library.
    foreach ($copy in @("engine", "engine.new")) { $null = Remove-OwnedItem (Join-Path $LibraryDir $copy) }
    $null = Remove-OwnedItem $LogsDir
    $shared = Join-Path $env:LOCALAPPDATA "Luminary"
    if ((Test-Path -LiteralPath $shared) -and -not (Get-ChildItem -LiteralPath $shared -Force)) { $null = Remove-OwnedItem $shared }
    Get-ChildItem -LiteralPath $env:TEMP -Directory -Filter "luminary-setup-*" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^luminary-setup-[0-9a-f]{32}$' } |
        ForEach-Object { $null = Remove-OwnedItem $_.FullName }
    Write-Step "Luminary is removed."
    Confirm-LibraryRemoval
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
    $answer = Read-Host "Email it to the Luminary developer at $ReportAddress? Your mail app opens with the report filled in, and nothing is sent until you press Send. [y/N]"
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
