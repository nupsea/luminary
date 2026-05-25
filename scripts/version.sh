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

if [ "$#" -eq 0 ]; then
    python3 - "$PYPROJECT" "$PKG" <<'PY'
import re, sys
pyproject, pkg = sys.argv[1], sys.argv[2]
m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', open(pyproject).read())
print("backend: ", m.group(1) if m else "?")
m = re.search(r'"version"\s*:\s*"([^"]+)"', open(pkg).read())
print("frontend:", m.group(1) if m else "?")
PY
    exit 0
fi

VERSION="$1"
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+.].*)?$ ]]; then
    echo "Invalid version: $VERSION (expected semver, e.g. 0.2.0)" >&2
    exit 1
fi

python3 - "$PYPROJECT" "$PKG" "$VERSION" <<'PY'
import re, sys
pyproject, pkg, version = sys.argv[1], sys.argv[2], sys.argv[3]

text = open(pyproject).read()
text, n = re.subn(r'(?m)^(version\s*=\s*")[^"]+(")', rf'\g<1>{version}\g<2>', text, count=1)
assert n == 1, "no version field found in pyproject.toml"
open(pyproject, "w").write(text)

text = open(pkg).read()
text, n = re.subn(r'("version"\s*:\s*")[^"]+(")', rf'\g<1>{version}\g<2>', text, count=1)
assert n == 1, "no version field found in package.json"
open(pkg, "w").write(text)
PY

echo "Set version to $VERSION (backend/pyproject.toml + frontend/package.json)"
