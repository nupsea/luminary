# Records every python.exe exit with a non-zero status to $args[0], until this process is stopped.
# CI runs it beside the backend suite: a crashed xdist worker leaves only "node down", and the
# exit status is what tells a native crash (0xC...) from a terminate or a signal (#211).
param([Parameter(Mandatory)][string]$Out)

New-Item -ItemType File -Force -Path $Out | Out-Null
Register-CimIndicationEvent -ClassName Win32_ProcessStopTrace -SourceIdentifier ProcessExits `
    -Filter "ProcessName = 'python.exe'" | Out-Null
while ($true) {
    $e = Wait-Event -SourceIdentifier ProcessExits -Timeout 5
    if (-not $e) { continue }
    $p = $e.SourceEventArgs.NewEvent
    if ($p.ExitStatus -ne 0) {
        $line = "{0:o} pid={1} parent={2} exit=0x{3:X8}" -f (Get-Date), $p.ProcessID, $p.ParentProcessID, [uint32]$p.ExitStatus
        Add-Content -Path $Out -Value $line
    }
    Remove-Event -EventIdentifier $e.EventIdentifier
}
