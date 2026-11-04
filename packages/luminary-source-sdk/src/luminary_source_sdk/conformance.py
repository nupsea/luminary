"""Check a connector against a source whose table of contents is known.

Run it in the connector's own environment:

    uv run python -m luminary_source_sdk.conformance my_package:MySource truth.json

`truth.json` is the ground truth, written by hand from the source, never from the connector:

    {"input": {"url": "https://example.com/book/"},
     "toc": ["Introduction", "Getting Started", ...],
     "chrome": ["text that appears only in the site's navigation or footer"],
     "credentials": {}}

`--luminary <Luminary backend dir>` also imports the bundle through Luminary's own importer
and checks what it reads. Exit status 0 when every check passes.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from luminary_source_sdk.protocol import PLACEHOLDER_TERMS
from luminary_source_sdk.testing import run


@dataclass(frozen=True)
class Truth:
    """What the source holds, decided by reading it."""

    input: dict[str, Any]
    toc: list[str]
    chrome: list[str] = field(default_factory=list)
    credentials: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Truth:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(raw["input"], list(raw["toc"]), list(raw.get("chrome", [])),
                   dict(raw.get("credentials", {})))  # fmt: skip


@dataclass(frozen=True)
class Finding:
    check: str
    passed: bool
    detail: str = ""


def _norm(heading: str) -> str:
    return " ".join(heading.split()).casefold()


class _Text(HTMLParser):
    _HIDDEN = frozenset({"script", "style", "template"})

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        self._hidden += tag in self._HIDDEN

    def handle_endtag(self, tag: str) -> None:
        self._hidden -= tag in self._HIDDEN and self._hidden > 0

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def visible_text(raw: str, suffix: str) -> str:
    """A section file's text as a reader sees it: HTML without its tags."""
    if suffix == ".md":
        return raw
    parser = _Text()
    parser.feed(raw)
    return " ".join(" ".join(parser.parts).split())


def _ordered(found: list[str], toc: list[str]) -> int:
    """How many of `found` appear in `toc`'s order: the longest common subsequence."""
    prev = [0] * (len(toc) + 1)
    for a in found:
        row = [0]
        for j, b in enumerate(toc):
            row.append(prev[j] + 1 if a == b else max(prev[j + 1], row[j]))
        prev = row
    return prev[-1]


def check_description(desc: dict[str, Any], truth: Truth) -> list[Finding]:
    terms = desc.get("terms") or {}
    missing = [k for k in ("name", "version", "licence") if not desc.get(k)]
    missing += [f"terms.{k}" for k in ("statement", "url") if not terms.get(k)]
    if terms.get("url") and not str(terms["url"]).startswith("https://"):
        missing.append("an https terms.url")
    if str(terms.get("statement", "")).strip() == PLACEHOLDER_TERMS:
        missing.append("the source's terms, quoted (the template's placeholder is still there)")
    missing += [f"a URL prefix, not {p!r}" for p in desc.get("url_prefixes") or []
                if not re.match(r"^https?://[^/\s]+/", str(p))]  # fmt: skip
    url = str(truth.input.get("url", ""))
    claims = any(url.startswith(p) for p in desc.get("url_prefixes") or [])
    return [
        Finding("describe", not missing, f"missing: {', '.join(missing)}" if missing else ""),
        Finding("claims the link", claims, "" if claims else f"no url_prefix takes {url}"),
    ]


def check_events(events: list[dict[str, Any]]) -> list[Finding]:
    last = events[-1] if events else {}
    fractions = [e["fraction"] for e in events if e.get("event") == "progress"]
    steady = all(a <= b for a, b in zip(fractions, fractions[1:]))
    failed = f"{last.get('code')}: {last.get('message')}" if last.get("event") == "error" else ""
    return [
        Finding("fetch", last.get("event") == "result", failed or "no result event"),
        Finding("progress", steady, "" if steady else f"progress went backwards: {fractions}"),
    ]


def check_sections(sections: list[tuple[str, str]], truth: Truth) -> list[Finding]:
    """(heading, visible text) in reading order, against the ground truth."""
    found = [_norm(h) for h, _ in sections]
    toc = [_norm(h) for h in truth.toc]
    missing = [h for h, n in zip(truth.toc, toc) if n not in found]
    extra = [h for h, _ in sections if _norm(h) not in toc]
    in_toc = [n for n in found if n in toc]
    in_order = _ordered(in_toc, toc) == len(in_toc)
    empty = [h for h, text in sections if not text.replace(h.strip(), "", 1).strip()]
    chrome = sorted({c for c in truth.chrome for _, text in sections if c in text})
    return [
        Finding("pages found", not missing, f"missing {len(missing)}: {missing[:10]}"),
        Finding("no extra pages", not extra, f"{len(extra)} not in the TOC: {extra[:10]}"),
        Finding("section order", in_order, "" if in_order else "sections are out of TOC order"),
        Finding("no empty sections", not empty, f"empty: {empty[:10]}"),
        Finding("chrome stripped", not chrome, f"navigation text kept: {chrome}"),
    ]


def bundle_sections(bundle: Path) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    sections = []
    for entry in manifest.get("sections", []):
        path = bundle / entry["file"]
        sections.append((entry["heading"], visible_text(path.read_text("utf-8"), path.suffix)))
    return manifest, sections


def check_manifest(manifest: dict[str, Any], desc: dict[str, Any]) -> list[Finding]:
    named = manifest.get("connector") or {}
    same = (named.get("name"), named.get("version")) == (desc.get("name"), desc.get("version"))
    terms = manifest.get("terms") == desc.get("terms")
    return [
        Finding("manifest names the connector", same, f"manifest says {named}"),
        Finding("manifest carries the terms", terms, "terms differ from describe"),
    ]


def no_app_import(entry: str) -> Finding:
    """A connector never imports Luminary's `app`: it would bring the core, and its licence,
    along. Read from the connector package's source, since the check may run beside `app`."""
    spec = importlib.util.find_spec(entry.partition(":")[0].split(".")[0])
    roots = list(spec.submodule_search_locations or []) if spec else []
    files = [p for r in roots for p in Path(r).rglob("*.py")]
    if spec and spec.origin and not roots:
        files = [Path(spec.origin)]
    found = sorted({f"{p.name}:{n.lineno}" for p in files for n in ast.walk(ast.parse(
        p.read_text(encoding="utf-8"))) if _imports_app(n)})  # fmt: skip
    return Finding("no app import", bool(files) and not found,
                   f"imports app at {found[:5]}" if files else "connector source not found")


def _imports_app(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(a.name.split(".")[0] == "app" for a in node.names)
    return isinstance(node, ast.ImportFrom) and node.level == 0 and (
        (node.module or "").split(".")[0] == "app"
    )


def luminary_importer(backend: Path) -> list[str]:
    """The command that runs Luminary's importer from a checkout's backend directory."""
    return ["uv", "run", "--directory", str(backend), "python", "-m", "app.scripts.check_bundle"]


def import_with_luminary(bundle: Path, importer: list[str], truth: Truth) -> list[Finding]:
    """The bundle through Luminary's importer (`app.scripts.check_bundle`), and what it reads."""
    proc = subprocess.run([*importer, str(bundle.resolve())], capture_output=True, text=True)
    try:
        read = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return [Finding("Luminary imports it", False, proc.stderr.strip()[-500:])]
    if "error" in read:
        return [Finding("Luminary imports it", False, read["error"])]
    text = " ".join(s["text"] for s in read.get("sections", []))
    chrome = sorted(c for c in truth.chrome if c in text)
    return [
        Finding("Luminary imports it", True, f"{len(read.get('sections', []))} sections"),
        Finding("chrome stripped after import", not chrome, f"navigation text kept: {chrome}"),
    ]


def conform(
    entry: str, truth: Truth, dest: Path, importer: list[str] | None = None
) -> list[Finding]:
    """Every check, in the order a reviewer reads them."""
    described = run(entry, "describe")[-1]
    desc = described.get("data") or {}
    findings = check_description(desc, truth)
    events = run(entry, "fetch", input=truth.input, credentials=truth.credentials, dest=dest)
    findings += check_events(events)
    findings.append(no_app_import(entry))
    if not (dest / "manifest.json").is_file():
        return findings
    manifest, sections = bundle_sections(dest)
    findings += check_manifest(manifest, desc)
    findings += check_sections(sections, truth)
    if importer is not None:
        findings += import_with_luminary(dest, importer, truth)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m luminary_source_sdk.conformance")
    parser.add_argument("entry", help="the connector, package.module:Class")
    parser.add_argument("truth", type=Path, help="the ground-truth JSON")
    parser.add_argument("--out", type=Path, help="where to keep the bundle (default: discarded)")
    parser.add_argument("--luminary", type=Path, help="a Luminary checkout's backend directory")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as scratch:
        dest = args.out or Path(scratch) / "bundle"
        importer = luminary_importer(args.luminary.resolve()) if args.luminary else None
        findings = conform(args.entry, Truth.load(args.truth), dest, importer)
    for f in findings:
        print(f"{'PASS' if f.passed else 'FAIL'}  {f.check}{'' if f.passed else ': ' + f.detail}")
    return 0 if all(f.passed for f in findings) else 1


if __name__ == "__main__":
    sys.exit(main())

