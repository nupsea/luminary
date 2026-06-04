#!/usr/bin/env bash
# check_powershell.sh — run the PowerShell syntax gate when pwsh is available.
#
# pwsh is preinstalled on GitHub's ubuntu-latest runners (so this runs in CI) but
# is usually absent on dev machines (where it skips with a note, like the public
# import guard). Keeps install.ps1 and the start.ps1 it generates from regressing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v pwsh >/dev/null 2>&1; then
    echo "[check_powershell] pwsh not found — skipping PowerShell syntax check (install PowerShell to run it locally)."
    exit 0
fi

pwsh -NoProfile -File "$REPO_ROOT/scripts/check_powershell.ps1"
