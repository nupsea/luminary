#!/usr/bin/env python3
"""Assert every backend router and top-level frontend page declares a tier.

Each must be referenced in surface-manifest.json or be on an explicit allow-list
of cross-cutting / always-on surfaces. Forces new routers/pages to pick a tier.
Wired into `make lint`.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "surface-manifest.json"
ROUTERS = REPO / "backend" / "app" / "routers"
PAGES = REPO / "frontend" / "src" / "pages"

# Always-on / cross-cutting routers that intentionally have no surface entry.
ROUTER_ALLOWLIST = {"settings"}
# Legacy pages kept for compatibility; not part of any current surface.
PAGE_ALLOWLIST = {"Evals"}


def manifest_routers(data: dict) -> set[str]:
    out: set[str] = set()
    for s in data["surfaces"]:
        out.update((s.get("backend") or {}).get("routers", []))
    return out


def manifest_components(data: dict) -> set[str]:
    out: set[str] = set()
    for s in data["surfaces"]:
        fe = s.get("frontend") or {}
        if fe.get("component"):
            out.add(fe["component"])
        out.update(fe.get("components") or [])
    return out


def main() -> int:
    data = json.loads(MANIFEST.read_text())
    errors: list[str] = []

    covered_routers = manifest_routers(data) | ROUTER_ALLOWLIST
    for f in sorted(ROUTERS.glob("*.py")):
        if f.stem == "__init__":
            continue
        if f.stem not in covered_routers:
            errors.append(f"router app/routers/{f.name} is not in the manifest or allow-list")

    covered_pages = {c.split("/")[-1] for c in manifest_components(data)} | PAGE_ALLOWLIST
    for f in sorted(PAGES.glob("*.tsx")):
        if f.stem not in covered_pages:
            errors.append(f"page src/pages/{f.name} is not in the manifest or allow-list")

    if errors:
        print("surface-manifest.json coverage check FAILED:")
        for e in errors:
            print(f"  - {e}")
        print("Add a surface entry in surface-manifest.json, or add to the allow-list in this script.")
        return 1

    print("surface-manifest.json coverage OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
