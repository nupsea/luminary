#!/usr/bin/env python3
"""Fail when a dependency that ships in an installer has a licence the policy does not allow (I-71).

Runs in `make ci`, so the PR that adds or bumps a dependency is the one that fails.

The shipping set is what the installers install: `uv export --group full` (the same
command `scripts/desktop/lib.sh` stages), every non-dev package in
`frontend/package-lock.json`, and every crate the desktop shell links or builds with on a
target the installers build (`cargo metadata --filter-platform`, #534). Dev tools never ship, so
they are not checked.

Each licence string must match an allowed pattern and no review pattern in
`scripts/licence_policy.json`. A review-pattern licence ships only under an exception
recording the exact string, a reason and an issue; when the string changes, the
exception stops applying and the package fails until someone re-reads it. An SPDX expression
is judged by every licence it names, OR as much as AND, so an unrecognised licence beside a
permissive one is caught rather than passed. A package whose metadata states no licence, or
that is not installed on this platform, needs a `declared` entry naming the licence and where
it was read.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POLICY = REPO / "scripts" / "licence_policy.json"
# A License field longer than this is the licence text itself, not its name.
SHORT_LICENCE_FIELD = 100
# Field values that name no licence; the classifiers decide (cloudscraper, python-dateutil).
UNINFORMATIVE = {"UNKNOWN", "DUAL LICENSE", "OTHER", "OSI APPROVED"}


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def shipping_python() -> list[str]:
    uv = shutil.which("uv") or "uv"
    out = subprocess.run(  # noqa: S603 -- fixed arguments, no user input
        [
            uv,
            "export",
            "--directory",
            str(REPO / "backend"),
            "--frozen",
            "--no-emit-project",
            "--no-default-groups",
            "--group",
            "full",
            "--format",
            "requirements-txt",
            "--no-hashes",
            "--quiet",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    names = {
        _normalise(re.split(r"[=;\s\[]", line, maxsplit=1)[0])
        for line in out.splitlines()
        if re.match(r"[A-Za-z0-9]", line)
    }
    return sorted(names)


def python_licence(name: str) -> str | None:
    try:
        meta = metadata.metadata(name)
    except metadata.PackageNotFoundError:
        return None
    if meta.get("License-Expression"):
        return meta["License-Expression"].strip()
    field = (meta.get("License") or "").strip()
    # A field holding the full text names the licence on its first line (tiktoken).
    name = field.splitlines()[0].strip() if field else ""
    if len(name) > SHORT_LICENCE_FIELD or name.upper() in UNINFORMATIVE:
        name = ""
    classifiers = [
        c.split("::")[-1].strip()
        for c in meta.get_all("Classifier") or []
        if c.startswith("License ::")
    ]
    return "; ".join(filter(None, [name, ", ".join(classifiers)])) or None


def shipping_npm() -> dict[str, str | None]:
    lock = json.loads((REPO / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    found: dict[str, str | None] = {}
    for path, entry in lock["packages"].items():
        # Native binaries for one os/cpu run under node, never inside the browser bundle.
        if not path or entry.get("dev") or entry.get("link") or "os" in entry or "cpu" in entry:
            continue
        name, licence = path.rsplit("node_modules/", 1)[-1], entry.get("license")
        # Two copies under different licences are two decisions.
        key = name if found.get(name, licence) == licence else f"{name}@{entry.get('version')}"
        found[key] = licence
    return found


def npm_dependants(name: str) -> list[str]:
    lock = json.loads((REPO / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    return sorted(
        {
            path.rsplit("node_modules/", 1)[-1] or "frontend"
            for path, entry in lock["packages"].items()
            if name in (entry.get("dependencies") or {})
        }
    )


def python_dependants(name: str) -> list[str]:
    uv = shutil.which("uv") or "uv"
    out = subprocess.run(  # noqa: S603 -- fixed arguments, no user input
        [
            uv,
            "tree",
            "--directory",
            str(REPO / "backend"),
            "--frozen",
            "--invert",
            "--package",
            name,
            "--depth",
            "1",
            "--no-default-groups",
            "--group",
            "full",
            "--quiet",
        ],
        check=False,
        capture_output=True,
        text=True,
    ).stdout
    # "└── luminary v0.17.0 (group: full)" -> "luminary"
    return [
        m.group(1)
        for line in out.splitlines()[1:]
        if (m := re.match(r"[\s│├└─]*([A-Za-z0-9_.-]+) v", line))
    ][:5]


# What the installers build (`.github/workflows/desktop-installers.yml`, release-macos-app.yml).
SHIPPED_TARGETS = ("aarch64-apple-darwin", "x86_64-pc-windows-msvc", "x86_64-unknown-linux-gnu")
# The phone's shell (#449). Its crates are keyed `rust-mobile:`, so no desktop exception applies:
# the mobile client is Apache-2.0 and ships nothing a review pattern catches (#534).
MOBILE_TARGETS = ("aarch64-linux-android",)


def shipping_rust(
    manifest: Path = REPO / "src-tauri" / "Cargo.toml", targets: tuple[str, ...] = SHIPPED_TARGETS
) -> dict[str, str | None]:
    """Crates a shell links or builds with on a shipped target; never dev-dependencies."""
    cargo = shutil.which("cargo")
    if cargo is None:
        raise FileNotFoundError("cargo")
    found: dict[str, str | None] = {}
    for target in targets:
        out = subprocess.run(  # noqa: S603 -- fixed arguments, no user input
            [
                cargo,
                "metadata",
                "--format-version",
                "1",
                "--locked",
                "--filter-platform",
                target,
                "--manifest-path",
                str(manifest),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        _crates_shipped(json.loads(out), found)
    return found


def _crates_shipped(meta: dict, found: dict[str, str | None]) -> None:
    packages = {p["id"]: p for p in meta["packages"]}
    nodes = {n["id"]: n for n in meta["resolve"]["nodes"]}
    members = set(meta["workspace_members"])
    reached: set[str] = set()
    stack = list(members)
    while stack:
        for dep in nodes[stack.pop()]["deps"]:
            shipped = any(k["kind"] in (None, "build") for k in dep["dep_kinds"])
            if shipped and dep["pkg"] not in reached:
                reached.add(dep["pkg"])
                stack.append(dep["pkg"])
    for pid in sorted(reached - members):
        crate = packages[pid]
        name, licence = crate["name"], crate.get("license")
        key = name if found.get(name, licence) == licence else f"{name}@{crate['version']}"
        found[key] = licence


def _classify_text(licence: str, policy: dict) -> str:
    if any(re.search(p, licence, re.IGNORECASE) for p in policy["review"]):
        return "review"
    if any(re.search(p, licence, re.IGNORECASE) for p in policy["allowed"]):
        return "allowed"
    return "unrecognised"


_RANK = {"allowed": 0, "unrecognised": 1, "review": 2}
_SPDX = re.compile(r"\(|\)|[A-Za-z0-9.+-]+")


def _spdx_verdict(licence: str, policy: dict) -> str | None:
    """The verdict of an SPDX expression, or None when *licence* is not one ("MIT License")."""
    text = licence.replace("/", " OR ")
    tokens = _SPDX.findall(text)
    if "".join(tokens) != re.sub(r"\s+", "", text):
        return None
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> str:
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def operand() -> str:
        if peek() == "(":
            take()
            verdict = expression()
            if take() != ")":
                raise ValueError
            return verdict
        token = take()
        if token in ("AND", "OR", "WITH", ")"):
            raise ValueError
        if peek() == "WITH":
            take()
            take()
        return _classify_text(token, policy)

    def conjunction() -> str:
        verdicts = [operand()]
        while peek() == "AND":
            take()
            verdicts.append(operand())
        return max(verdicts, key=_RANK.__getitem__)

    def expression() -> str:
        verdicts = [conjunction()]
        while peek() == "OR":
            take()
            verdicts.append(conjunction())
        return max(verdicts, key=_RANK.__getitem__)

    try:
        verdict = expression()
    except (ValueError, IndexError):
        return None
    return verdict if pos == len(tokens) else None


def classify(licence: str, policy: dict) -> str:
    return _spdx_verdict(licence, policy) or _classify_text(licence, policy)


def check(shipped: dict[str, str | None], policy: dict) -> list[str]:
    problems = []
    for key, stated in sorted(shipped.items()):
        declared = policy["declared"].get(key)
        licence = stated
        if licence is None:
            if declared is None:
                problems.append(
                    f"{key}: no licence in its metadata, or not installed here; "
                    "add a `declared` entry with the licence and its source"
                )
                continue
            licence = declared["licence"]
        verdict = classify(licence, policy)
        exception = policy["exceptions"].get(key)
        if verdict == "allowed":
            continue
        if exception and exception["licence"] == licence:
            continue
        if exception:
            problems.append(
                f"{key}: licence is now {licence!r}, the exception was granted for "
                f"{exception['licence']!r}; re-read it before updating the entry"
            )
        elif verdict == "review":
            problems.append(
                f"{key}: {licence!r} needs a decision before it ships "
                "(an `exceptions` entry with a reason and an issue)"
            )
        else:
            problems.append(
                f"{key}: {licence!r} matches no allowed pattern; if it is a "
                "permissive licence, add its pattern to `allowed`"
            )
    for key in sorted(set(policy["exceptions"]) - set(shipped)):
        problems.append(f"{key}: has an exception but no longer ships; remove the entry")
    return problems


def main() -> int:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    shipped = {f"python:{n}": python_licence(n) for n in shipping_python()}
    shipped |= {f"npm:{n}": lic for n, lic in shipping_npm().items()}
    try:
        shipped |= {f"rust:{n}": lic for n, lic in shipping_rust().items()}
        mobile = shipping_rust(REPO / "src-tauri-mobile" / "Cargo.toml", MOBILE_TARGETS)
        shipped |= {f"rust-mobile:{n}": lic for n, lic in mobile.items()}
    except FileNotFoundError:
        # CI always has cargo; a backend-only checkout may not, and is told so.
        if os.environ.get("CI"):
            print("FAIL cargo not found: the shipped Rust crates were not checked", file=sys.stderr)
            return 1
        print("note: cargo not found here, so the Rust crates were not checked", file=sys.stderr)
    problems = check(shipped, policy)
    if not problems:
        excepted = sum(k in policy["exceptions"] for k in shipped)
        print(f"licences ok: {len(shipped)} shipped packages, {excepted} under an exception")
        return 0
    for p in problems:
        ecosystem, name = p.split(":", 2)[:2]
        by = {"python": python_dependants, "npm": npm_dependants}.get(ecosystem, lambda _: [])(name)
        print(
            f"FAIL {p}" + (f"\n     pulled in by: {', '.join(by)}" if by else ""), file=sys.stderr
        )
    print(
        f"\n{len(problems)} licence problem(s); policy and how to resolve each: "
        f"{POLICY.relative_to(REPO)}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
