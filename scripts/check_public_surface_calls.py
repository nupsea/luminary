#!/usr/bin/env python3
"""Assert the public build never calls a router only `full` mode mounts.

Routers are mounted per mode (`main.py` filters ROUTER_REGISTRY through
`enabled_routers(mode)`), and every shipped path runs LUMINARY_MODE=public --
the Tauri supervisor, the installer, docker-compose and the release workflow.
A `public` surface calling a `full`-only router therefore 404s in every build a
user ever sees, while working perfectly in `make dev`.

That is not hypothetical: the Progress page read its document count from
/monitoring/overview, and `monitoring` is a full-mode surface. It rendered 0
documents in every shipped build for as long as the call existed, because the
frontend's error branch fell back to a zero.

Wired into `make lint`.
"""

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "surface-manifest.json"
ROUTERS = REPO / "backend" / "app" / "routers"
FRONTEND = REPO / "frontend" / "src"

_MODE_ORDER = {"public": 0, "full": 1}

# Always mounted regardless of mode (see main.py: `_enabled | {"settings", "setup"}`).
ALWAYS_MOUNTED = {"settings", "setup"}

# Paths served by main.py itself rather than by a router.
NON_ROUTER_PREFIXES = ("/health", "/healthz", "/version", "/ready", "/startup")

_CALL_RE = re.compile(r"""api(?:Get|Post|Put|Patch|Delete)\s*<[^>]*>\s*\(\s*[`"']([^`"']+)""")
_CALL_RE_NOGENERIC = re.compile(r"""api(?:Get|Post|Put|Patch|Delete)\s*\(\s*[`"']([^`"']+)""")


def surfaces_for_mode(data: dict, mode: str) -> list[dict]:
    rank = _MODE_ORDER[mode]
    return [s for s in data["surfaces"] if _MODE_ORDER[s["mode"]] <= rank]


def enabled_routers(data: dict, mode: str) -> set[str]:
    out = set(ALWAYS_MOUNTED)
    for s in surfaces_for_mode(data, mode):
        out.update((s.get("backend") or {}).get("routers", []))
    return out


def router_prefixes() -> dict[str, str]:
    """Map router module stem -> its APIRouter prefix."""
    out: dict[str, str] = {}
    pat = re.compile(r"""APIRouter\((?:[^)]*?)prefix\s*=\s*["']([^"']+)["']""", re.S)
    for f in sorted(ROUTERS.glob("*.py")):
        if f.stem == "__init__":
            continue
        m = pat.search(f.read_text())
        if m:
            out[f.stem] = m.group(1)
    return out


def full_only_files(data: dict) -> set[Path]:
    """Files that only ever render in full mode, so may call full-only routers."""
    exempt: set[Path] = set()
    for s in data["surfaces"]:
        if s["mode"] != "full":
            continue
        fe = s.get("frontend") or {}
        for comp in [fe.get("component"), *(fe.get("components") or [])]:
            if not comp:
                continue
            base = FRONTEND / comp  # e.g. "pages/Monitoring", "components/evals"
            # Mirrors check_manifest_schema.component_exists: a dir, a .tsx or a .ts.
            exempt.add(base.with_suffix(".tsx"))
            exempt.add(base.with_suffix(".ts"))
            if base.is_dir():
                exempt.update(base.rglob("*.ts"))
                exempt.update(base.rglob("*.tsx"))
    return exempt


def resolve_router(path: str, prefixes: dict[str, str]) -> str | None:
    """Longest-prefix match from an API path to the router that serves it."""
    best: tuple[int, str] | None = None
    for name, prefix in prefixes.items():
        if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
            if best is None or len(prefix) > best[0]:
                best = (len(prefix), name)
    return best[1] if best else None


def main() -> int:
    data = json.loads(MANIFEST.read_text())
    public = enabled_routers(data, "public")
    full = enabled_routers(data, "full")
    full_only = full - public
    if not full_only:
        print("public-surface call check OK (no full-only routers declared)")
        return 0

    prefixes = router_prefixes()
    exempt = full_only_files(data)
    errors: list[str] = []

    for f in sorted([*FRONTEND.rglob("*.ts"), *FRONTEND.rglob("*.tsx")]):
        if f in exempt or f.name.endswith(".test.ts") or f.name.endswith(".test.tsx"):
            continue
        text = f.read_text()
        calls = set(_CALL_RE.findall(text)) | set(_CALL_RE_NOGENERIC.findall(text))
        for call in calls:
            path = call.split("?")[0]
            if not path.startswith("/") or path.startswith(NON_ROUTER_PREFIXES):
                continue
            name = resolve_router(path, prefixes)
            if name in full_only:
                rel = f.relative_to(REPO)
                errors.append(f"{rel} calls {path} -> router '{name}', which public mode does not mount")

    if errors:
        print("public-surface call check FAILED:")
        for e in errors:
            print(f"  - {e}")
        print(
            "\nEvery shipped build runs LUMINARY_MODE=public, so these calls 404 for users.\n"
            "Move the data onto a public router, or move the caller onto a full-mode surface."
        )
        return 1

    print(f"public-surface call check OK ({len(full_only)} full-only routers guarded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
