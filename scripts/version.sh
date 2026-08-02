#!/usr/bin/env bash
# version.sh — read or set the shared Luminary version across backend + frontend.
#
#   scripts/version.sh           print the current backend + frontend versions
#   scripts/version.sh 0.2.0     set both to 0.2.0 (keeps them in sync)
#
# Edits are targeted regex replacements so file formatting is preserved.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYPROJECT="$REPO_ROOT/backend/pyproject.toml"
PKG="$REPO_ROOT/frontend/package.json"
# The desktop shell carries the version twice more. Missed here, the .app
# reports a stale version in Finder and About while the backend reports the new
# one -- and the DMG filename comes from a different source again.
TAURI_CONF="$REPO_ROOT/src-tauri/tauri.conf.json"
CARGO="$REPO_ROOT/src-tauri/Cargo.toml"

if [ "$#" -eq 0 ]; then
    python3 - "$PYPROJECT" "$PKG" "$TAURI_CONF" "$CARGO" <<'PY'
import re, sys
pyproject, pkg, tauri_conf, cargo = sys.argv[1:5]


def show(label, path, pattern):
    m = re.search(pattern, open(path).read())
    print(f"{label:<10}", m.group(1) if m else "?")


show("backend:", pyproject, r'(?m)^version\s*=\s*"([^"]+)"')
show("frontend:", pkg, r'"version"\s*:\s*"([^"]+)"')
show("tauri:", tauri_conf, r'"version"\s*:\s*"([^"]+)"')
show("cargo:", cargo, r'(?m)^version\s*=\s*"([^"]+)"')
PY
    exit 0
fi

VERSION="$1"
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+.].*)?$ ]]; then
    echo "Invalid version: $VERSION (expected semver, e.g. 0.2.0)" >&2
    exit 1
fi

python3 - "$PYPROJECT" "$PKG" "$TAURI_CONF" "$CARGO" "$VERSION" <<'PY'
import re, sys
pyproject, pkg, tauri_conf, cargo, version = sys.argv[1:6]


def bump(path, pattern, label):
    text = open(path).read()
    text, n = re.subn(pattern, rf'\g<1>{version}\g<2>', text, count=1)
    assert n == 1, f"no version field found in {label}"
    open(path, "w").write(text)


bump(pyproject, r'(?m)^(version\s*=\s*")[^"]+(")', "pyproject.toml")
bump(pkg, r'("version"\s*:\s*")[^"]+(")', "package.json")
bump(tauri_conf, r'("version"\s*:\s*")[^"]+(")', "tauri.conf.json")
bump(cargo, r'(?m)^(version\s*=\s*")[^"]+(")', "src-tauri/Cargo.toml")
PY

echo "Set version to $VERSION"
echo "  backend/pyproject.toml, frontend/package.json,"
echo "  src-tauri/tauri.conf.json, src-tauri/Cargo.toml"
