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

A script that reaches a route through a tool rather than curl (S212 runs
`run_eval.py`) declares it, so the mode check sees it:

    # smoke-calls: /evals/environment

A script that asserts an endpoint stays *gone* declares it:

    # smoke-expects-absent: /code/execute

Those are the scripts this check must never flag. S140 guards a code-execution
sandbox that was deleted for security, and a flag inviting someone to "repair" it
by restoring the route is the one outcome worse than the drift.

**It also holds every script to `scripts/smoke/lib.sh`**, which is what lets one
suite run against the dev backend and the bundled app alike:

- each script sources it, and none defines its own base or names port 7820 --
  nine spellings of the base URL once made the suite unpointable at anything else;
- none writes to a literal `/tmp`, which native Windows Python cannot open;
- none runs the frontend toolchain (`npx`, `npm`, `tsc`, `vitest`): a machine with
  only the installed app has no Node, and `make ci` already builds, type-checks and
  tests the frontend -- thirteen scripts failed that way on the first Windows run;
- none uploads from stdin (`-F file=@/dev/stdin`), which curl.exe cannot open, and
  none puts non-ASCII in a curl data argument, which Windows re-encodes to its ANSI
  code page before curl sees it -- both failed silently on the second Windows run;
- none reads `$BASE/openapi.json`: the schema is at the origin's root and its paths
  carry `/api` in public mode, so scripts use `smoke_openapi`;
- a script that reports SKIP exits `$SMOKE_SKIP`, never 0: seventeen printed SKIP
  and exited 0, so the runner counted every one of them as a pass;
- a script that calls a route public mode does not mount declares
  `smoke_require_mode full`, so it is reported as skipped against the bundled app
  rather than failed -- and a script that declares it without needing it is
  flagged, because a needless skip is lost coverage.

Wired into `make lint`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SMOKE = REPO / "scripts" / "smoke"

# `curl ... "${BASE}/documents/${DOC_ID}/sections"`. Both brace styles appear.
_CALL = re.compile(r"\$\{?BASE\}?\"?(/[A-Za-z0-9_${}/.-]*)")
_EXPECTS_ABSENT = re.compile(r"^#\s*smoke-expects-absent:\s*(\S+)", re.M)
# A route the script reaches through a tool rather than curl, e.g. run_eval.py.
_DECLARED_CALL = re.compile(r"^#\s*smoke-calls:\s*(\S+)", re.M)

_SHELL_VAR = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

# Served by FastAPI itself and deliberately absent from `paths`.
_BUILTINS = {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}

_SOURCES_LIB = 'source "$(dirname "$0")/lib.sh"'
_REQUIRES_FULL = re.compile(r"^\s*smoke_require_mode full\s*$", re.M)
_FRONTEND_TOOLCHAIN = re.compile(r"\b(?:npx|npm|tsc|vitest)\b|node_modules")
# Native curl.exe on Windows cannot open /dev/stdin, so `-F file=@/dev/stdin` exits 26.
_STDIN_UPLOAD = re.compile(r"@(?:/dev/stdin|-)(?:[;\"\']|$)")
_SCHEMA_UNDER_BASE = re.compile(r"\$\{?BASE\}?/openapi\.json")
_CURL_DATA = re.compile(r"(?:^|\s)(?:-d|--data(?:-raw|-binary)?)\s")
_SKIP_MESSAGE = re.compile(r'^\s*echo\s+["\']SKIP')
_OWN_BASE = re.compile(r"^\s*(?:export\s+)?(?:BASE|BASE_URL|API|API_BASE)=", re.M)
# Public mode mounts the whole API under this prefix (main.py `_API_PREFIX`).
_PUBLIC_PREFIX = "/api"


def _code_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


def hygiene_violations(text: str) -> list[str]:
    """What stops one script from running against any base on any OS."""
    found: list[str] = []
    code = _code_lines(text)
    if not any(line.strip() == _SOURCES_LIB for line in code):
        found.append(f"does not `{_SOURCES_LIB}`")
    if _OWN_BASE.search("\n".join(code)):
        found.append("defines its own base URL; lib.sh sets BASE from LUMINARY_BASE_URL")
    if any("7820" in line for line in code):
        found.append("names port 7820; use $BASE")
    if any("/tmp/" in line or line.rstrip().endswith("/tmp") for line in code):
        found.append("writes to a literal /tmp; use $SMOKE_TMP or mktemp")
    if any(_FRONTEND_TOOLCHAIN.search(line) for line in code):
        found.append("runs the frontend toolchain; that belongs in `make ci`, not smoke")
    if any(_STDIN_UPLOAD.search(line) for line in code):
        found.append("uploads from stdin, which curl.exe cannot read; write to $SMOKE_TMP")
    if any(_SCHEMA_UNDER_BASE.search(line) for line in code):
        found.append("reads $BASE/openapi.json, a 404 on the bundled app; use smoke_openapi")
    for i, line in enumerate(code):
        if _SKIP_MESSAGE.match(line) and any(
            nxt.strip() == "exit 0" for nxt in code[i + 1 : i + 3]
        ):
            found.append('prints SKIP but exits 0, which counts as a pass; exit "$SMOKE_SKIP"')
            break
    if any(_CURL_DATA.search(line) and not line.isascii() for line in code):
        found.append(
            "passes non-ASCII in a curl data argument, which Windows re-encodes to its"
            " ANSI code page; escape it as \\uXXXX in the JSON"
        )
    return found


def route_paths(mode: str = "full") -> set[str]:
    """The live surface, read off the app's routes rather than its schema.

    The routes keep their converters -- `/tags/{tag_id:path}` -- and the schema
    does not. That distinction is the whole check: without it a parameter has to
    be allowed to swallow several segments, and `/documents/upload` then matches
    `/documents/{document_id}` as though `upload` were an id, which is exactly
    the rename this is supposed to catch.
    """
    code = (
        "import json;"
        "from app.main import app;"
        "print(json.dumps(sorted({r.path for r in app.routes if hasattr(r,'path')})))"
    )
    out = subprocess.run(
        ["uv", "run", "python", "-c", code],
        cwd=REPO / "backend",
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "LUMINARY_MODE": mode},
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


class Surface:
    """The routes one mode mounts, as matchers over called paths."""

    def __init__(self, route_set: set[str]) -> None:
        declared = [p for p in route_set if not p.startswith("/{full_path")]
        self.patterns = [matcher(p) for p in declared]
        self.literal = {p for p in declared if "{" not in p} | _BUILTINS

    def serves(self, path: str) -> bool:
        return path in self.literal or any(pat.match(path) for pat in self.patterns)


def main() -> int:
    full = Surface(route_paths("full"))
    public = Surface({p.removeprefix(_PUBLIC_PREFIX) or "/" for p in route_paths("public")})

    missing: list[tuple[str, str]] = []
    hygiene: list[tuple[str, str]] = []
    undeclared: list[tuple[str, str]] = []
    needless: list[str] = []
    checked = 0
    scripts = sorted(SMOKE.glob("S*.sh"))
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        hygiene += [(script.name, v) for v in hygiene_violations(text)]
        absent = {p.rstrip("/") for p in _EXPECTS_ABSENT.findall(text)}
        full_only: list[str] = []
        for raw in _CALL.findall(text) + _DECLARED_CALL.findall(text):
            path = normalise(raw)
            if path == "/":
                continue
            checked += 1
            if path in absent:
                continue
            if not full.serves(path):
                missing.append((script.name, path))
            elif not public.serves(path):
                full_only.append(path)
        declares_full = bool(_REQUIRES_FULL.search(text))
        if full_only and not declares_full:
            undeclared.append((script.name, full_only[0]))
        elif declares_full and not full_only:
            needless.append(script.name)

    failed = False
    if missing:
        failed = True
        print(f"{len(missing)} smoke call(s) target paths the API no longer serves:\n")
        for name, path in sorted(set(missing)):
            print(f"  {name:12} {path}")
        print(
            "\nEach needs a decision, not a mechanical repair: renamed, deliberately\n"
            "removed, or genuinely lost. If the script asserts the endpoint stays gone,\n"
            "declare it with `# smoke-expects-absent: <path>` -- never bring the route\n"
            "back to make this pass.\n"
        )
    if hygiene:
        failed = True
        print(f"{len(hygiene)} smoke script problem(s) that tie it to one base or OS:\n")
        for name, problem in hygiene:
            print(f"  {name:12} {problem}")
        print("\nSee scripts/smoke/lib.sh.\n")
    if undeclared:
        failed = True
        print(f"{len(undeclared)} script(s) call a route public mode does not mount:\n")
        for name, path in undeclared:
            print(f"  {name:12} {path}")
        print(
            "\nAdd `smoke_require_mode full` after sourcing lib.sh, so the script is\n"
            "skipped against the bundled app instead of failing there.\n"
        )
    if needless:
        failed = True
        print(f"{len(needless)} script(s) require full mode but call only public routes:\n")
        print("  " + " ".join(needless))
        print("\nRemove `smoke_require_mode full`: the skip hides coverage the bundled app has.\n")
    if failed:
        return 1

    print(f"smoke scripts OK: {checked} calls across {len(scripts)} scripts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
