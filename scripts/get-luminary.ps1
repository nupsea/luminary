# get-luminary.ps1 -- install the Luminary desktop app on Windows in one command.
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
#
# Errors throw rather than exit: under `irm | iex`, exit closes the user's window.

$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1 downloads an order of magnitude slower with the bar drawn.
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-Step([string]$message) { Write-Host "==> $message" }

function Find-LuminaryInstall {
    $keys = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($key in $keys) {
        $entry = Get-ItemProperty $key -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -eq "Luminary" } | Select-Object -First 1
        if ($entry -and $entry.InstallLocation) {
            $dir = $entry.InstallLocation.Trim('"')
            if (Test-Path $dir) { return $dir }
        }
    }
    foreach ($dir in @("$env:LOCALAPPDATA\Luminary", "$env:LOCALAPPDATA\Programs\Luminary")) {
        if (Test-Path $dir) { return $dir }
    }
    return $null
}

function Find-LuminaryExe([string]$dir) {
    Get-ChildItem -Path $dir -Filter "*.exe" -File |
        Where-Object { $_.Name -notlike "uninstall*" } | Select-Object -First 1
}

function Get-ReleaseAsset($release, [string]$pattern) {
    $release.assets | Where-Object { $_.name -like $pattern } | Select-Object -First 1
}

function Install-Luminary {
    if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64" -and $env:PROCESSOR_ARCHITEW6432 -ne "AMD64") {
        throw "Luminary is built for x64 Windows only (this is $env:PROCESSOR_ARCHITECTURE)."
    }

    $existing = Find-LuminaryInstall
    if ($existing) {
        $running = Get-Process -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -and $_.Path.StartsWith($existing, [StringComparison]::OrdinalIgnoreCase) }
        if ($running) {
            throw "Luminary is running. Close it, then run this again; your library is kept."
        }
    }

    $work = Join-Path $env:TEMP ("luminary-setup-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $work -Force | Out-Null
    try {
        if ($env:LUMINARY_INSTALLER) {
            if (-not (Test-Path $env:LUMINARY_INSTALLER)) { throw "No such file: $env:LUMINARY_INSTALLER" }
            $setup = (Resolve-Path $env:LUMINARY_INSTALLER).Path
        } else {
            $repo = if ($env:LUMINARY_REPO) { $env:LUMINARY_REPO } else { "nupsea/luminary" }
            $version = if ($env:LUMINARY_VERSION) { $env:LUMINARY_VERSION } else { "latest" }
            $api = "https://api.github.com/repos/$repo/releases/latest"
            if ($version -ne "latest") { $api = "https://api.github.com/repos/$repo/releases/tags/v$($version.TrimStart('v'))" }
            $release = Invoke-RestMethod -Uri $api -Headers @{ Accept = "application/vnd.github+json" }

            $asset = Get-ReleaseAsset $release "Luminary_*_x64-setup.exe"
            if (-not $asset) { throw "Release $($release.tag_name) has no Windows installer; it may predate one." }
            $sum = Get-ReleaseAsset $release "$($asset.name).sha256"
            if (-not $sum) { throw "Release $($release.tag_name) has no checksum for $($asset.name); refusing to install unverified." }

            $setup = Join-Path $work $asset.name
            Write-Step "Downloading $($asset.name) ($([math]::Round($asset.size / 1MB)) MB)"
            Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $setup -UseBasicParsing
            Invoke-WebRequest -Uri $sum.browser_download_url -OutFile "$setup.sha256" -UseBasicParsing
            $expected = ((Get-Content "$setup.sha256" -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
            $actual = (Get-FileHash -Path $setup -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($expected -ne $actual) {
                throw "Checksum mismatch for $($asset.name) (expected $expected, got $actual)."
            }
        }

        Write-Step "Installing for $env:USERNAME (no administrator rights needed)"
        $proc = Start-Process -FilePath $setup -ArgumentList "/S" -Wait -PassThru
        if ($proc.ExitCode -ne 0) { throw "The installer exited with code $($proc.ExitCode)." }
    } finally {
        Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
    }

    $dir = Find-LuminaryInstall
    if (-not $dir) { throw "The installer finished but Luminary's install folder was not found." }
    $exe = Find-LuminaryExe $dir
    if (-not $exe) { throw "No Luminary executable in $dir." }
    Write-Step "Installed to $dir. Remove it from Settings > Apps; your library is kept."

    if ($env:LUMINARY_NO_LAUNCH -ne "1") {
        Write-Step "Opening Luminary. First launch downloads its models and takes a few minutes."
        Start-Process -FilePath $exe.FullName
    }
}

Install-Luminary
