"""Write the third-party notices for a stage, or check an existing file still matches it.

    third_party_notices.py --site SITE --runtime-license FILE --npm-root DIR
                           --version V --out FILE [--check]

Exits 1 naming every shipped package without a licence text, so a new dependency
cannot reach an installer without its notice (#378). Texts a package does not ship
come from third_party/, keyed in third_party/vendored.json.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
from email.parser import Parser
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENDORED_DIR = HERE / "third_party"
SOURCE_URL = "https://github.com/nupsea/luminary/tree/v{version}"
LICENCE_FILE = re.compile(
    r"^(licen[cs]e|copying|notice|copyright|authors)([-_.][\w.-]*)?$", re.IGNORECASE
)
# A module named license.js is code, not a notice.
CODE_SUFFIXES = {
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".map",
    ".json",
    ".py",
    ".pyc",
    ".pyi",
    ".css",
}
# A License field longer than this is the licence text itself, not its name.
SHORT_LICENCE_FIELD = 100


class Component:
    def __init__(self, ecosystem: str, name: str, version: str, licence: str):
        self.ecosystem = ecosystem
        self.name = name
        self.version = version
        self.licence = licence or "unstated"
        self.texts: list[tuple[str, str]] = []

    @property
    def copyleft_network(self) -> bool:
        return "agpl" in self.licence.lower() or "affero" in self.licence.lower()


def _read_text(path: Path) -> str | None:
    data = path.read_bytes()
    if b"\0" in data[:4096]:
        return None
    return _normalise(data.decode("utf-8", errors="replace"))


def _normalise(text: str) -> str:
    # One newline convention, or --check fails on a file it just wrote (\r\n reads back as \n).
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _licence_files(root: Path, recursive: bool) -> list[Path]:
    found = []
    candidates = root.rglob("*") if recursive else root.iterdir()
    for p in sorted(candidates):
        rel = p.relative_to(root).parts
        # A nested node_modules package is its own lockfile entry.
        if not p.is_file() or "node_modules" in rel or p.suffix.lower() in CODE_SUFFIXES:
            continue
        if LICENCE_FILE.match(p.name) or (recursive and "licenses" in rel[:-1]):
            found.append(p)
    return found


def _attach(component: Component, files: list[Path], base: Path) -> None:
    for f in files:
        text = _read_text(f)
        label = f.relative_to(base).as_posix()
        if text is None:
            text = f"(Shipped in the bundle as an archive: {label})"
        component.texts.append((label, text))


def _vendored(ecosystem: str, name: str) -> Path | None:
    table = json.loads((VENDORED_DIR / "vendored.json").read_text())[ecosystem]
    for pattern, file in table.items():
        if fnmatch.fnmatchcase(name, pattern):
            return VENDORED_DIR / file
    return None


def python_components(site: Path) -> list[Component]:
    out = []
    for dist in sorted(site.glob("*.dist-info")):
        meta = Parser().parsestr((dist / "METADATA").read_text(errors="replace"))
        field = (meta.get("License") or "").strip()
        classifiers = [
            c.split("::")[-1].strip()
            for c in meta.get_all("Classifier") or []
            if c.startswith("License ::")
        ]
        licence = (
            meta.get("License-Expression")
            or (field if len(field) <= SHORT_LICENCE_FIELD and "\n" not in field else "")
            or ", ".join(classifiers)
        )
        c = Component("python", meta["Name"], meta["Version"], licence)
        _attach(c, _licence_files(dist, recursive=True), site)
        if not c.texts:
            tops = (
                (dist / "top_level.txt").read_text().split()
                if (dist / "top_level.txt").exists()
                else []
            )
            for top in tops:
                if (site / top).is_dir():
                    _attach(c, _licence_files(site / top, recursive=False), site)
        if not c.texts and (len(field) > SHORT_LICENCE_FIELD or "\n" in field):
            c.texts.append(("METADATA License field", _normalise(field)))
        out.append(c)
    return out


def npm_components(root: Path) -> list[Component]:
    lock = json.loads((root / "package-lock.json").read_text())
    out = []
    for path, entry in sorted(lock["packages"].items()):
        # Native binaries for one os/cpu run under node, never inside the browser bundle.
        if not path or entry.get("dev") or entry.get("link") or "os" in entry or "cpu" in entry:
            continue
        pkg_dir = root / path
        if not pkg_dir.is_dir():
            continue
        pkg = json.loads((pkg_dir / "package.json").read_text())
        licence = pkg.get("license")
        if isinstance(licence, dict):
            licence = licence.get("type")
        c = Component("npm", pkg["name"], pkg.get("version", ""), licence or "")
        # Recursive: a package that vendors code carries its notices below the top level.
        _attach(c, _licence_files(pkg_dir, recursive=True), root)
        out.append(c)
    return out


def _fill_from_vendored(components: list[Component]) -> list[Component]:
    missing = []
    for c in components:
        if c.texts:
            continue
        vendored = _vendored(c.ecosystem, c.name)
        if vendored is None:
            missing.append(c)
        else:
            c.texts.append((f"upstream {vendored.name}", _read_text(vendored)))
    return missing


def render(components: list[Component], runtime: Component, version: str) -> str:
    agpl = sorted({c.name for c in components if c.copyleft_network})
    lines = [f"Third-party software in Luminary {version}", "=" * 60, ""]
    lines.append("Luminary's own source code is licensed under Apache-2.0 (LUMINARY-LICENSE).")
    if agpl:
        lines += [
            f"This distribution also contains {' and '.join(agpl)}, licensed under the GNU Affero",
            "General Public License v3.0, so the distribution as a whole is offered under",
            "AGPL-3.0. That includes users of a Luminary server over a network.",
        ]
    lines += [
        f"Complete corresponding source: {SOURCE_URL.format(version=version)}",
        "",
        "Ollama and llama.cpp: OLLAMA-LICENSE and LLAMA.CPP-LICENSE beside this file.",
        "",
        "Contents",
        "-" * 8,
    ]
    everything = [runtime, *components]
    if agpl:
        # pymupdf names its licence without shipping the text.
        agpl_text = Component("licence", "GNU Affero General Public License", "3.0", "AGPL-3.0")
        agpl_text.texts.append(("agpl-3.0.txt", _read_text(VENDORED_DIR / "agpl-3.0.txt")))
        everything.insert(0, agpl_text)
    for c in everything:
        lines.append(f"{c.ecosystem:8} {c.name} {c.version}  [{c.licence}]")
    seen: dict[str, str] = {}
    for c in everything:
        lines += ["", "=" * 60, f"{c.name} {c.version} ({c.ecosystem}) -- {c.licence}", "=" * 60]
        for label, text in c.texts:
            digest = hashlib.sha256(text.encode()).hexdigest()
            if digest in seen:
                lines.append(f"{label}: same text as {seen[digest]}")
            else:
                seen[digest] = f"{c.name} {c.version}"
                lines += [f"--- {label}", text]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", type=Path, required=True)
    ap.add_argument("--runtime-license", type=Path, required=True)
    ap.add_argument("--npm-root", type=Path, required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--check", action="store_true", help="fail if --out differs from the stage")
    args = ap.parse_args()

    components = python_components(args.site) + npm_components(args.npm_root)
    missing = _fill_from_vendored(components)
    if missing:
        for c in missing:
            print(
                f"no licence text: {c.ecosystem} {c.name} {c.version} [{c.licence}]",
                file=sys.stderr,
            )
        print(
            f"{len(missing)} shipped package(s) have no notice; add the upstream text under "
            f"{VENDORED_DIR.name}/ and key it in vendored.json",
            file=sys.stderr,
        )
        return 1

    runtime = Component("runtime", "CPython", sys.version.split()[0], "PSF-2.0")
    runtime.texts.append((args.runtime_license.name, _read_text(args.runtime_license)))
    notices = render(components, runtime, args.version)

    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != notices:
            print(f"{args.out} does not match the stage; re-run stage_notices.sh", file=sys.stderr)
            return 1
        print(f"notices match the stage: {len(components)} packages")
        return 0
    args.out.write_text(notices, encoding="utf-8", newline="\n")
    agpl = sum(c.copyleft_network for c in components)
    print(f"wrote {args.out}: {len(components)} packages, {agpl} AGPL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
