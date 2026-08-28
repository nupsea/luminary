#!/usr/bin/env python3
"""Assert the built public bundle contains no full-mode surface's code.

`surface-manifest.json` mode gating is a RUNTIME array filter
(`visibleSurfaces()` in frontend/src/lib/surfaceManifest.ts). It decides what
renders; it does not decide what is compiled in. A full-mode component that a
public-mode page imports statically therefore ships to every user, inert but
present -- the UI entry point is hidden and the router 404s, so nothing looks
wrong from outside.

Measured 2026-08-27 on a public build: `blog` rode into the Notes chunk via
`import { BlogPublishDialog }` in pages/Notes.tsx, and `feynman` into the
Learning chunk via `import { FeynmanDialog }` in components/reader/
DocumentReader.tsx. Both files already guarded rendering with
`isSurfaceVisible(...)`, which is exactly why it went unnoticed.

Routed full-mode pages (admin, monitoring, quality) were already clean: they are
reached through `lazy(() => import(...))` behind manifest-driven routing, so
nothing references them in a public build.

The probe is derived from the manifest rather than hand-listed: for every
full-only router, look for its URL prefix as a string literal in the emitted
JavaScript. A public bundle has no reason to contain "/blog/" -- if it does,
that surface's client code was compiled in.

Run AFTER `npm run build` (which defaults to public mode). Wired into `make ci`.
"""

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "surface-manifest.json"
ROUTERS = REPO / "backend" / "app" / "routers"
DIST = REPO / "frontend" / "dist" / "assets"

_MODE_ORDER = {"public": 0, "full": 1}
ALWAYS_MOUNTED = {"settings", "setup"}


def enabled_routers(data: dict, mode: str) -> set[str]:
    rank = _MODE_ORDER[mode]
    out = set(ALWAYS_MOUNTED)
    for s in data["surfaces"]:
        if _MODE_ORDER[s["mode"]] <= rank:
            out.update((s.get("backend") or {}).get("routers", []))
    return out


def router_prefixes() -> dict[str, str]:
    pat = re.compile(r"""APIRouter\((?:[^)]*?)prefix\s*=\s*["']([^"']+)["']""", re.S)
    out: dict[str, str] = {}
    for f in sorted(ROUTERS.glob("*.py")):
        if f.stem == "__init__":
            continue
        m = pat.search(f.read_text())
        if m:
            out[f.stem] = m.group(1)
    return out


def main() -> int:
    if not DIST.is_dir():
        print(
            f"ERROR: no build at {DIST}. Run `npm run build` in frontend/ first -- "
            "this check reads the emitted bundle, not the source.",
            file=sys.stderr,
        )
        return 2

    data = json.loads(MANIFEST.read_text())
    full_only = enabled_routers(data, "full") - enabled_routers(data, "public")
    prefixes = router_prefixes()

    chunks = sorted(DIST.glob("*.js"))
    if not chunks:
        print(f"ERROR: {DIST} holds no .js chunks; nothing was scanned.", file=sys.stderr)
        return 2
    blobs = {p.name: p.read_text(errors="ignore") for p in chunks}

    errors: list[str] = []
    checked = 0
    for router in sorted(full_only):
        prefix = prefixes.get(router)
        if not prefix:
            continue
        # Anchored on a non-path boundary. The manifest is itself bundled and
        # lists component paths like "components/blog/BlogPublishDialog", so a
        # bare "/blog/" substring matches that embedded JSON and reports a leak
        # that is not one -- while skipping any probe the manifest contains
        # (the first attempt) silently drops `blog`, which is a real leak. An
        # API path literal is preceded by a quote; a component path by a word
        # character. Discriminate on that.
        probe = re.compile(r"(?<![\w/])" + re.escape(prefix) + r"/")
        checked += 1
        hits = sorted(name for name, body in blobs.items() if probe.search(body))
        if hits:
            errors.append(
                f"  full-mode surface `{router}`: {prefix + '/'!r} found in {', '.join(hits)}"
            )

    if errors:
        print("Public bundle contains full-mode code:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        print(
            "\nA runtime `isSurfaceVisible()` guard hides the UI but still compiles the\n"
            "component in. Import it so the mode folds at build time instead:\n"
            '  const Dlg = LUMINARY_MODE === "full"\n'
            '    ? lazy(() => import("@/components/..."))\n'
            "    : null\n"
            "`LUMINARY_MODE` is a vite `define`, so the false branch and its dynamic\n"
            "import are dropped from a public build entirely.",
            file=sys.stderr,
        )
        return 1

    print(f"public bundle check OK ({checked} full-only routers probed, {len(chunks)} chunks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
