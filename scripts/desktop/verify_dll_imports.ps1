# Every DLL the installed app imports must ship inside it or be part of Windows itself.
#
# The runners have the Visual C++ runtime installed, so an app that needs it launches
# there and fails on a clean machine with "VCRUNTIME140.dll was not found". A runtime
# DLL counts as shipped only in the importing executable's own folder (the loader looks
# there first) or, for a library, anywhere in the install.
param([Parameter(Mandatory = $true)][string]$Root)
$ErrorActionPreference = "Stop"

# Installed by the Visual C++ redistributable, never by Windows.
$Redistributable = '^(vcruntime\d+(_\d+)?|msvcp\d+(_\w+)?|msvcr\d+|vcomp\d+|concrt\d+|vccorlib\d+|mfc\d+\w*|atl\d+)\.dll$'
# Installed by a graphics driver; the engine loads its GPU backends only where one is.
$Driver = '^(nvcuda|nvml|nvapi64|vulkan-1|amdhip64(_\d+)?|amd_comgr\w*|hiprtc\w*|opencl|nvrtc\w*)\.dll$'

function Get-PeImports([string]$path) {
    $fs = [IO.File]::OpenRead($path)
    $br = New-Object IO.BinaryReader($fs)
    try {
        if ($fs.Length -lt 0x40) { return @() }
        $fs.Position = 0x3C
        $pe = $br.ReadInt32()
        if ($pe -le 0 -or $pe -gt $fs.Length - 24) { return @() }
        $fs.Position = $pe
        if ($br.ReadUInt32() -ne 0x4550) { return @() }
        $fs.Position = $pe + 6
        $sectionCount = $br.ReadUInt16()
        $fs.Position = $pe + 20
        $optionalSize = $br.ReadUInt16()
        $optional = $pe + 24
        $fs.Position = $optional
        $magic = $br.ReadUInt16()
        # The import directory is data directory 1.
        $fs.Position = $optional + $(if ($magic -eq 0x20B) { 112 } else { 96 }) + 8
        $importRva = $br.ReadUInt32()
        if ($importRva -eq 0) { return @() }
        $sections = for ($i = 0; $i -lt $sectionCount; $i++) {
            $fs.Position = $optional + $optionalSize + 40 * $i + 8
            $virtualSize = $br.ReadUInt32(); $va = $br.ReadUInt32(); $rawSize = $br.ReadUInt32(); $raw = $br.ReadUInt32()
            [pscustomobject]@{ Va = [long]$va; Size = [long][Math]::Max($virtualSize, $rawSize); Raw = [long]$raw }
        }
        $toOffset = {
            param($rva)
            foreach ($s in $sections) { if ($rva -ge $s.Va -and $rva -lt $s.Va + $s.Size) { return $rva - $s.Va + $s.Raw } }
            return -1
        }
        $names = @()
        $descriptor = & $toOffset $importRva
        while ($descriptor -ge 0 -and $descriptor + 20 -le $fs.Length) {
            $fs.Position = $descriptor + 12
            $nameRva = $br.ReadUInt32()
            if ($nameRva -eq 0) { break }
            $at = & $toOffset $nameRva
            if ($at -lt 0) { break }
            $fs.Position = $at
            $bytes = New-Object System.Collections.Generic.List[byte]
            while ($bytes.Count -lt 256) { $b = $br.ReadByte(); if ($b -eq 0) { break }; $bytes.Add($b) }
            $names += [Text.Encoding]::ASCII.GetString($bytes.ToArray()).ToLowerInvariant()
            $descriptor += 20
        }
        return $names
    } finally {
        $br.Close()
    }
}

$system32 = Join-Path $env:SystemRoot "System32"
$files = @(Get-ChildItem -LiteralPath $Root -Recurse -File | Where-Object { $_.Extension -in @('.exe', '.dll', '.pyd') })
$shipped = @{}
foreach ($f in $files) { if ($f.Extension -ieq ".dll") { $shipped[$f.Name.ToLowerInvariant()] = $true } }

$scanned = 0; $imports = 0; $system = 0; $driver = 0
$failures = New-Object System.Collections.Generic.List[string]
foreach ($f in $files) {
    $names = @(Get-PeImports $f.FullName)
    if ($names.Count -gt 0) { $scanned++ }
    foreach ($name in $names) {
        $imports++
        if ($name -like "api-ms-win-*" -or $name -like "ext-ms-*") { $system++; continue }
        $beside = Test-Path -LiteralPath (Join-Path $f.DirectoryName $name)
        if ($name -match $Redistributable) {
            if ($beside -or ($f.Extension -ine ".exe" -and $shipped.ContainsKey($name))) { continue }
            $failures.Add("$($f.FullName.Substring($Root.Length + 1)) needs $name, from the Visual C++ redistributable, and the install has no copy where it looks")
            continue
        }
        if ($beside -or $shipped.ContainsKey($name)) { continue }
        if ($name -match $Driver) { $driver++; continue }
        if (Test-Path -LiteralPath (Join-Path $system32 $name)) { $system++; continue }
        $failures.Add("$($f.FullName.Substring($Root.Length + 1)) needs $name, which is neither shipped nor part of Windows")
    }
}

"scanned $scanned binaries with $imports imports: $system from Windows, $driver from a graphics driver, the rest shipped"
# A parser that reads nothing would pass everything.
if ($scanned -lt 20 -or $system -eq 0) { throw "only $scanned binaries had readable imports; the import reader is not working" }
if ($failures.Count -gt 0) {
    $failures | Sort-Object -Unique | ForEach-Object { "MISSING: $_" }
    throw "$($failures.Count) imports would fail on a Windows without them"
}
