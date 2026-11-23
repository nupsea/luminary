"""`luminary-connector`: start, run and check a connector without a Luminary checkout.

    luminary-connector new my-source              # a project to fill in
    luminary-connector run pkg.module:Class describe
    luminary-connector run pkg.module:Class fetch --url https://... --dest out/
    luminary-connector validate out/              # what Luminary would refuse

`validate` checks what the SDK writes. Luminary validates every bundle again when it imports
one; `python -m luminary_source_sdk.conformance --luminary <backend>` runs that importer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from luminary_source_sdk import protocol
from luminary_source_sdk.bundle import _SAFE_NAME, BUNDLE_VERSION
from luminary_source_sdk.conformance import visible_text
from luminary_source_sdk.testing import run

_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# `services/parser.MIN_SECTION_CHARS` in the core: a shorter section is not imported.
MIN_SECTION_CHARS = 50


def validate(bundle: Path) -> list[str]:
    """What is wrong with the bundle at *bundle*, empty when nothing is."""
    try:
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"manifest.json is missing or not JSON: {exc}"]
    if not isinstance(manifest, dict):
        return ["manifest.json is not an object"]
    problems = []
    if manifest.get("bundle_version") != BUNDLE_VERSION:
        problems.append(f"bundle_version is not {BUNDLE_VERSION}")
    connector = manifest.get("connector") or {}
    if not (connector.get("name") and connector.get("version")):
        problems.append("connector needs a name and a version")
    if not str(manifest.get("title") or "").strip():
        problems.append("title is empty")
    problems += _terms(manifest.get("terms") or {})
    kind = (manifest.get("media") or {}).get("kind")
    if kind not in protocol.MEDIA:
        problems.append(f"media.kind {kind!r} is not one of {protocol.MEDIA}")
    sections = manifest.get("sections") or []
    if kind == "text" and not sections:
        problems.append("a text bundle needs at least one section")
    seen: set[str] = set()
    for section in sections:
        sid = section.get("id")
        if sid in seen:
            problems.append(f"section id {sid!r} is used twice")
        seen.add(sid)
        problems += _file(bundle, section.get("file"), f"section {sid!r}", (".html", ".md"))
    if (
        kind == "text"
        and sections
        and not problems
        and not any(len(_text(bundle, s["file"]).strip()) >= MIN_SECTION_CHARS for s in sections)
    ):
        problems.append(f"no section has {MIN_SECTION_CHARS} characters of text")
    if manifest.get("cover") is not None:
        problems += _file(bundle, manifest["cover"], "cover", None)
    return problems


def _text(bundle: Path, rel: str) -> str:
    return visible_text((bundle / rel).read_text(encoding="utf-8"), PurePosixPath(rel).suffix)


def _terms(terms: dict[str, Any]) -> list[str]:
    statement = str(terms.get("statement") or "").strip()
    if not statement:
        return ["terms.statement is empty"]
    if statement == protocol.PLACEHOLDER_TERMS:
        return ["terms.statement is still the template's placeholder"]
    if not str(terms.get("url") or "").startswith("https://"):
        return ["terms.url is not https"]
    return []


def _file(bundle: Path, rel: Any, what: str, suffixes: tuple[str, ...] | None) -> list[str]:
    rel = str(rel or "")
    if not _SAFE_NAME.match(rel) or ".." in PurePosixPath(rel).parts:
        return [f"{what}: {rel!r} is not a safe path inside the bundle"]
    if suffixes is not None and not rel.endswith(suffixes):
        return [f"{what}: {rel} is neither .html nor .md"]
    if not (bundle / rel).is_file():
        return [f"{what}: {rel} is not in the bundle"]
    return []


def new(name: str, parent: Path) -> Path:
    """A connector project named *name* under *parent*, from the template."""
    if not _NAME.match(name):
        raise SystemExit(f"{name!r}: use lower-case letters, digits and -")
    package = "luminary_" + name.replace("-", "_")
    cls = "".join(part.capitalize() for part in name.split("-"))
    root = parent / name
    if root.exists():
        raise SystemExit(f"{root} already exists")
    values = {"name": name, "package": package, "cls": cls}
    for rel, text in _TEMPLATE.items():
        path = root / rel.format(**values)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.format(**values), encoding="utf-8")
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="luminary-connector", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_new = sub.add_parser("new", help="start a connector project")
    p_new.add_argument("name")
    p_new.add_argument("--dir", type=Path, default=Path.cwd())
    p_run = sub.add_parser("run", help="send one request to a connector, as Luminary does")
    p_run.add_argument("entry", help="package.module:Class")
    p_run.add_argument("op", choices=protocol.OPS)
    p_run.add_argument("--url", help="the link, for preview and fetch")
    p_run.add_argument("--input", default="{}", help="the request's input, as JSON")
    p_run.add_argument("--credentials", default="{}", help="credentials, as JSON")
    p_run.add_argument("--dest", type=Path, help="where fetch writes the bundle")
    p_val = sub.add_parser("validate", help="check a bundle")
    p_val.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)

    if args.command == "new":
        print(new(args.name, args.dir))
        return 0
    if args.command == "validate":
        return _report(validate(args.bundle))
    inp = json.loads(args.input) | ({"url": args.url} if args.url else {})
    creds = json.loads(args.credentials)
    with tempfile.TemporaryDirectory() as scratch:
        dest = args.dest or Path(scratch) / "bundle"
        events = run(args.entry, args.op, input=inp, credentials=creds, dest=dest)
        for event in events:
            print(json.dumps(event, ensure_ascii=False))
        if events[-1].get("event") != "result":
            return 1
        return _report(validate(dest)) if args.op == "fetch" else 0


def _report(problems: list[str]) -> int:
    for problem in problems:
        print(f"FAIL  {problem}")
    if not problems:
        print("bundle ok")
    return 1 if problems else 0


_TEMPLATE = {
    "pyproject.toml": """[project]
name = "{name}"
version = "0.1.0"
description = "A Luminary connector."
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = ["luminary-source-sdk"]

[project.entry-points."luminary.connectors"]
{name} = "{package}:{cls}"

[dependency-groups]
dev = ["pytest"]

# Until the SDK is on PyPI. Pin a commit (`rev = "..."`) once the connector works.
[tool.uv.sources]
luminary-source-sdk = {{ git = "https://github.com/nupsea/luminary", subdirectory = "packages/luminary-source-sdk" }}

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{package}"]
""",
    "src/{package}/__init__.py": '''"""A Luminary connector: one web page, as one section. Replace what this source needs."""

from __future__ import annotations

from typing import Any

from luminary_source_sdk import PLACEHOLDER_TERMS, BundleWriter, ConnectorError, Report, Terms
from luminary_source_sdk.bases import UrlConnector
from luminary_source_sdk.client import PoliteClient
from luminary_source_sdk.pages import main_html


class {cls}(UrlConnector):
    NAME = "{name}"
    VERSION = "0.1.0"
    LABEL = "{cls}"
    # Quote what your source's own terms say about downloading and automated use, and where.
    # Install and the conformance kit refuse the placeholder.
    TERMS = Terms(statement=PLACEHOLDER_TERMS, url="https://example.com/terms")
    URL_PREFIXES = ("https://example.com/",)

    def fetch(
        self, input: dict[str, Any], credentials: dict[str, Any], bundle: BundleWriter, report: Report
    ) -> None:
        url = self.claimed_url(input)
        _, page = PoliteClient(self.user_agent()).get_text(url)
        report(0.5, "reading the page")
        title, main = main_html(page)
        if not main:
            raise ConnectorError("source", f"{{url}} has no <main>")
        bundle.add_section("page", title or url, html=main, source_url=url)
        self.finish(bundle, title=title or url, source_url=url)
''',
    "tests/test_{package}.py": """from luminary_source_sdk.testing import run, serve_pages

from {package} import {cls}

PAGE = "<title>A page</title><main><h1>A page</h1><p>Its text, long enough to keep.</p></main>"


def test_a_page_becomes_one_section(tmp_path, monkeypatch):
    with serve_pages({{"/a": PAGE}}) as base:
        monkeypatch.setattr({cls}, "URL_PREFIXES", (base + "/",))
        events = run("{package}:{cls}", "fetch", input={{"url": base + "/a"}}, dest=tmp_path / "b")
    assert events[-1]["event"] == "result", events[-1]
""",
    "README.md": """# {name}

A Luminary connector. Fill in `TERMS`, `URL_PREFIXES` and `fetch` in `src/{package}/__init__.py`.

    uv run pytest
    uv run luminary-connector run {package}:{cls} fetch --url https://example.com/a
""",
}


if __name__ == "__main__":
    sys.exit(main())
