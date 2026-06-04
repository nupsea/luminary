#!/usr/bin/env pwsh
# check_powershell.ps1 — static syntax gate for the repo's PowerShell scripts.
#
# Parses every scripts/*.ps1 with the PowerShell language parser and fails on any
# syntax error. It also re-parses here-strings assigned to a *ScriptContent
# variable, so a script that GENERATES another script (install.ps1 -> start.ps1)
# is validated too. No code is executed — parse only.
#
# Usage:  pwsh -NoProfile -File scripts/check_powershell.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptsDir = Join-Path $repoRoot "scripts"
$failed = $false

function Test-ParseErrors([string]$label, [string]$path, [string]$source) {
    $tokens = $null
    $errors = $null
    if ($source -ne $null) {
        [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors) | Out-Null
    } else {
        [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors) | Out-Null
    }
    if ($errors.Count -gt 0) {
        Write-Host ("FAIL  {0}" -f $label) -ForegroundColor Red
        foreach ($e in $errors) {
            Write-Host ("        line {0}: {1}" -f $e.Extent.StartLineNumber, $e.Message)
        }
        return $false
    }
    Write-Host ("OK    {0}" -f $label) -ForegroundColor Green
    return $true
}

$files = Get-ChildItem -Path $scriptsDir -Filter "*.ps1" -File
if ($files.Count -eq 0) {
    Write-Host "No .ps1 files found under $scriptsDir" -ForegroundColor Yellow
    exit 0
}

foreach ($file in $files) {
    if (-not (Test-ParseErrors $file.Name $file.FullName $null)) { $failed = $true }

    # Re-parse generated scripts embedded as @'...'@ assigned to *ScriptContent.
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
    $assignments = $ast.FindAll({
        param($n)
        ($n -is [System.Management.Automation.Language.AssignmentStatementAst]) -and
        ($n.Left.Extent.Text -match 'ScriptContent$') -and
        ($n.Right.Expression -is [System.Management.Automation.Language.StringConstantExpressionAst])
    }, $true)
    foreach ($a in $assignments) {
        $label = "{0} -> {1} (generated)" -f $file.Name, $a.Left.Extent.Text
        if (-not (Test-ParseErrors $label $null $a.Right.Expression.Value)) { $failed = $true }
    }
}

if ($failed) {
    Write-Host "PowerShell syntax check failed." -ForegroundColor Red
    exit 1
}
Write-Host "PowerShell syntax check passed." -ForegroundColor Green
