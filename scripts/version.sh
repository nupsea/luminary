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
# Both lockfiles record the workspace package's own version. Nothing wrote them
# here, so they kept the previous number until uv or cargo happened to run and
# rewrote them as a side effect -- which dirtied the tree at an unpredictable
# moment, and `make release` refuses a dirty tree. Two releases in a row stalled
# on it.
UV_LOCK="$REPO_ROOT/backend/uv.lock"
CARGO_LOCK="$REPO_ROOT/src-tauri/Cargo.lock"

if [ "$#" -eq 0 ]; then
    python3 - "$PYPROJECT" "$PKG" "$TAURI_CONF" "$CARGO" "$UV_LOCK" "$CARGO_LOCK" <<'PY'
import re, sys
pyproject, pkg, tauri_conf, cargo, uv_lock, cargo_lock = sys.argv[1:7]


def show(label, path, pattern):
    m = re.search(pattern, open(path).read())
    print(f"{label:<10}", m.group(1) if m else "?")


def lock_pattern(package: str) -> str:
    return rf'(?ms)^\[\[package\]\]\nname = "{re.escape(package)}"\nversion = "([^"]+)"'


show("backend:", pyproject, r'(?m)^version\s*=\s*"([^"]+)"')
show("frontend:", pkg, r'"version"\s*:\s*"([^"]+)"')
show("tauri:", tauri_conf, r'"version"\s*:\s*"([^"]+)"')
show("cargo:", cargo, r'(?m)^version\s*=\s*"([^"]+)"')
show("uv.lock:", uv_lock, lock_pattern("luminary-backend"))
show("Cargo.lock:", cargo_lock, lock_pattern("luminary-desktop"))
PY
    exit 0
fi

VERSION="$1"
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+.].*)?$ ]]; then
    echo "Invalid version: $VERSION (expected semver, e.g. 0.2.0)" >&2
    exit 1
fi

python3 - "$PYPROJECT" "$PKG" "$TAURI_CONF" "$CARGO" "$UV_LOCK" "$CARGO_LOCK" "$VERSION" <<'PY'
import re, sys
pyproject, pkg, tauri_conf, cargo, uv_lock, cargo_lock, version = sys.argv[1:8]


def bump(path, pattern, label):
    text = open(path).read()
    text, n = re.subn(pattern, rf'\g<1>{version}\g<2>', text, count=1)
    assert n == 1, f"no version field found in {label}"
    open(path, "w").write(text)


def lock_pattern(package: str) -> str:
    """Scoped to the workspace package's own block.

    A lockfile lists every dependency, and a dependency can legitimately sit at
    the version being replaced -- `libloading` was at 0.7.4 in Cargo.lock during
    the 0.7.5 bump. Anchoring on the [[package]] header and the name keeps the
    edit on the one entry that means "this repo".
    """
    return (
        rf'(?ms)^(\[\[package\]\]\nname = "{re.escape(package)}"\nversion = ")'
        rf'[^"]+(")'
    )


bump(pyproject, r'(?m)^(version\s*=\s*")[^"]+(")', "pyproject.toml")
bump(pkg, r'("version"\s*:\s*")[^"]+(")', "package.json")
bump(tauri_conf, r'("version"\s*:\s*")[^"]+(")', "tauri.conf.json")
bump(cargo, r'(?m)^(version\s*=\s*")[^"]+(")', "src-tauri/Cargo.toml")
# Targeted rather than `uv lock` / `cargo update`: re-resolving dependencies is
# not something a version bump should do quietly on the way to a tag.
bump(uv_lock, lock_pattern("luminary-backend"), "backend/uv.lock")
bump(cargo_lock, lock_pattern("luminary-desktop"), "src-tauri/Cargo.lock")
PY

echo "Set version to $VERSION"
echo "  backend/pyproject.toml, frontend/package.json,"
echo "  src-tauri/tauri.conf.json, src-tauri/Cargo.toml,"
echo "  backend/uv.lock, src-tauri/Cargo.lock"
