#!/usr/bin/env python3
"""Assert every path a smoke script calls still exists in the API surface.

`make smoke` needs a live backend and a local model, so it cannot run on a CI
runner -- which is how 48 of its scripts came to test endpoints that had been
renamed or deleted without anything noticing (#62). This check needs neither: it
reads the OpenAPI schema straight off the FastAPI app and compares it against the
URLs the scripts build.

**What it catches**: a call whose route is gone entirely -- the `/code/execute`,
`/chat/confusion-signals`, `/qa/history` and `/explain/glossary/*` classes, which
were four of the five in that report.

**What it cannot**: a rename into a slot the API still declares as a parameter.
`/documents/upload` matches `/documents/{document_id}` for the same reason
`/documents/nonexistent-s146-doc-id` does -- a 404 probe and a rename are the
same string shape, and 27 scripts legitimately probe 404s that way. Guessing
between them produces false alarms on a green suite, which is how a check stops
being read. `make smoke` catches that class by running it.

It catches drift, not behaviour. A script whose endpoint still exists but whose
assertions are wrong is `make smoke`'s job.

A script that asserts an endpoint stays *gone* declares it:

    # smoke-expects-absent: /code/execute

Those are the scripts this check must never flag. S140 guards a code-execution
sandbox that was deleted for security, and a flag inviting someone to "repair" it
by restoring the route is the one outcome worse than the drift.

Wired into `make lint`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SMOKE = REPO / "scripts" / "smoke"

# `curl ... "${BASE}/documents/${DOC_ID}/sections"`. Both brace styles appear.
_CALL = re.compile(r"\$\{?BASE\}?\"?(/[A-Za-z0-9_${}/.-]*)")
_EXPECTS_ABSENT = re.compile(r"^#\s*smoke-expects-absent:\s*(\S+)", re.M)

_SHELL_VAR = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

# Served by FastAPI itself and deliberately absent from `paths`.
_BUILTINS = {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}


def route_paths() -> list[str]:
    """The live surface, read off the app's routes rather than its schema.

    The routes keep their converters -- `/tags/{tag_id:path}` -- and the schema
    does not. That distinction is the whole check: without it a parameter has to
    be allowed to swallow several segments, and `/documents/upload` then matches
    `/documents/{document_id}` as though `upload` were an id, which is exactly
    the rename this is supposed to catch.
    """
    code = (
        "import json,os;"
        "os.environ.setdefault('LUMINARY_MODE','full');"
        "from app.main import app;"
        "print(json.dumps(sorted({r.path for r in app.routes if hasattr(r,'path')})))"
    )
    out = subprocess.run(
        ["uv", "run", "python", "-c", code],
        cwd=REPO / "backend",
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        print("could not read the OpenAPI schema:", file=sys.stderr)
        print(out.stderr[-2000:], file=sys.stderr)
        raise SystemExit(2)
    return set(json.loads(out.stdout.strip().splitlines()[-1]))


def normalise(raw: str) -> str:
    """A called URL reduced to the shape OpenAPI declares."""
    path = raw.split("?", maxsplit=1)[0].split("#", maxsplit=1)[0].rstrip("\"'&;|)")
    path = _SHELL_VAR.sub("{p}", path)
    path = _UUID.sub("{p}", path)
    return re.sub(r"/+", "/", path).rstrip("/") or "/"


def matcher(route_path: str) -> re.Pattern[str]:
    """A declared route as a regex over called paths.

    A parameter matches one segment, or several when the route declared
    `:path`. Anything may fill a parameter: smoke scripts put literal ids there
    to probe 404s (`/documents/nonexistent-s146-doc-id`), and those are
    indistinguishable from a renamed sub-resource.
    """
    parts = []
    for seg in route_path.strip("/").split("/"):
        if not seg.startswith("{"):
            parts.append(re.escape(seg))
        else:
            parts.append(r".+" if seg.endswith(":path}") else r"[^/]+")
    return re.compile("^/" + "/".join(parts) + "$")


def main() -> int:
    declared = [p for p in route_paths() if not p.startswith("/{full_path")]
    patterns = [matcher(p) for p in declared]
    literal = {p for p in declared if "{" not in p} | _BUILTINS

    missing: list[tuple[str, str]] = []
    checked = 0
    scripts = sorted(SMOKE.glob("S*.sh"))
    for script in scripts:
        text = script.read_text()
        absent = {p.rstrip("/") for p in _EXPECTS_ABSENT.findall(text)}
        for raw in _CALL.findall(text):
            path = normalise(raw)
            if path == "/":
                continue
            checked += 1
            if path in literal or path in absent:
                continue
            if any(pat.match(path) for pat in patterns):
                continue
            missing.append((script.name, path))

    if missing:
        print(f"{len(missing)} smoke call(s) target paths the API no longer serves:\n")
        for name, path in sorted(set(missing)):
            print(f"  {name:12} {path}")
        print(
            "\nEach needs a decision, not a mechanical repair: renamed, deliberately\n"
            "removed, or genuinely lost. If the script asserts the endpoint stays gone,\n"
            "declare it with `# smoke-expects-absent: <path>` -- never bring the route\n"
            "back to make this pass."
        )
        return 1

    print(f"smoke paths OK: {checked} calls across {len(scripts)} scripts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
