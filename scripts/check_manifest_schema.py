#!/usr/bin/env python3
"""Validate surface-manifest.json structure and that every reference resolves.

Exits non-zero on the first batch of violations. Wired into `make lint`.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "surface-manifest.json"
ROUTERS = REPO / "backend" / "app" / "routers"
FRONTEND_SRC = REPO / "frontend" / "src"

TIERS = {"public", "labs", "dev"}
KINDS = {"nav_tab", "feature", "service"}


def component_exists(rel: str) -> bool:
    base = FRONTEND_SRC / rel
    return base.is_dir() or base.with_suffix(".tsx").is_file() or base.with_suffix(".ts").is_file()


def main() -> int:
    data = json.loads(MANIFEST.read_text())
    errors: list[str] = []

    if data.get("version") != 1:
        errors.append(f"unsupported manifest version: {data.get('version')!r} (expected 1)")

    seen_ids: set[str] = set()
    seen_routes: dict[str, str] = {}

    for s in data.get("surfaces", []):
        sid = s.get("id", "<missing id>")

        if sid in seen_ids:
            errors.append(f"duplicate surface id: {sid}")
        seen_ids.add(sid)

        if s.get("tier") not in TIERS:
            errors.append(f"{sid}: invalid tier {s.get('tier')!r}")
        if s.get("kind") not in KINDS:
            errors.append(f"{sid}: invalid kind {s.get('kind')!r}")

        fe = s.get("frontend") or {}
        route = fe.get("route")
        component = fe.get("component")

        if s.get("kind") == "nav_tab" and (not route or not component):
            errors.append(f"{sid}: nav_tab requires frontend.route and frontend.component")

        if s.get("tier") == "labs" and not s.get("description"):
            errors.append(f"{sid}: labs surfaces require a description")

        if route:
            if route in seen_routes:
                errors.append(f"{sid}: duplicate frontend.route {route} (also {seen_routes[route]})")
            seen_routes[route] = sid

        for comp in [component, *(fe.get("components") or [])]:
            if comp and not component_exists(comp):
                errors.append(f"{sid}: frontend component not found under frontend/src/: {comp}")

        for router in (s.get("backend") or {}).get("routers", []):
            if not (ROUTERS / f"{router}.py").is_file():
                errors.append(f"{sid}: backend router not found: app/routers/{router}.py")

    if errors:
        print("surface-manifest.json schema check FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"surface-manifest.json schema OK ({len(seen_ids)} surfaces)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
