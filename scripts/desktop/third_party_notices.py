"""Write the third-party notices for a stage, or check an existing file still matches it.

    third_party_notices.py --site SITE --runtime-license FILE --runtime-build FILE
                           --npm-root DIR --cargo-manifest FILE --ollama FILE
                           --version V --out FILE [--check]

Exits 1 naming every shipped package without a licence text, so a new dependency
cannot reach an installer without its notice (#378). Texts a package does not ship
come from third_party/, keyed in third_party/vendored.json.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import re
import subprocess
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
GO_BUILDINFO = b"\xff Go buildinf:"


class NoticeError(Exception):
    pass


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
    table = json.loads((VENDORED_DIR / "vendored.json").read_text(encoding="utf-8"))[ecosystem]
    for pattern, file in table.items():
        if fnmatch.fnmatchcase(name, pattern):
            return VENDORED_DIR / file
    return None


def python_components(site: Path) -> list[Component]:
    out = []
    for dist in sorted(site.glob("*.dist-info")):
        meta = Parser().parsestr((dist / "METADATA").read_text(encoding="utf-8", errors="replace"))
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
                (dist / "top_level.txt").read_text(encoding="utf-8").split()
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
    lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
    out = []
    for path, entry in sorted(lock["packages"].items()):
        # Native binaries for one os/cpu run under node, never inside the browser bundle.
        if not path or entry.get("dev") or entry.get("link") or "os" in entry or "cpu" in entry:
            continue
        pkg_dir = root / path
        if not pkg_dir.is_dir():
            continue
        pkg = json.loads((pkg_dir / "package.json").read_text(encoding="utf-8"))
        licence = pkg.get("license")
        if isinstance(licence, dict):
            licence = licence.get("type")
        c = Component("npm", pkg["name"], pkg.get("version", ""), licence or "")
        # Recursive: a package that vendors code carries its notices below the top level.
        _attach(c, _licence_files(pkg_dir, recursive=True), root)
        out.append(c)
    return out


def _cargo_metadata(manifest: Path) -> dict:
    rustc = subprocess.run(  # noqa: S603 -- fixed arguments, no user input
        ["rustc", "-vV"],  # noqa: S607 -- the toolchain on PATH builds the shell
        capture_output=True,
        check=True,
    ).stdout.decode()
    host = re.search(r"^host: (\S+)", rustc, re.M).group(1)
    cmd = ["cargo", "metadata", "--format-version", "1", "--filter-platform", host]
    cmd += ["--manifest-path", str(manifest)]
    return json.loads(subprocess.run(cmd, capture_output=True, check=True).stdout)  # noqa: S603


def cargo_components(meta: dict) -> list[Component]:
    """Crates compiled into the shell: normal dependencies only, build and dev ones never ship."""
    pkgs = {p["id"]: p for p in meta["packages"]}
    nodes = {n["id"]: n for n in meta["resolve"]["nodes"]}
    seen, todo = set(), [meta["resolve"]["root"]]
    while todo:
        node = todo.pop()
        if node not in seen:
            seen.add(node)
            todo += [
                d["pkg"]
                for d in nodes[node]["deps"]
                if any(k["kind"] is None for k in d["dep_kinds"])
            ]
    out = []
    # A path dependency is this repository's own code.
    for p in sorted(
        (pkgs[i] for i in seen if pkgs[i]["source"]), key=lambda p: (p["name"], p["version"])
    ):
        c = Component("cargo", p["name"], p["version"], p.get("license") or "")
        crate = Path(p["manifest_path"]).parent
        _attach(c, _licence_files(crate, recursive=False), crate.parent)
        out.append(c)
    std = Component("cargo", "Rust standard library", "", "MIT OR Apache-2.0")
    std.texts.append(("upstream rust-std.txt", _read_text(VENDORED_DIR / "cargo" / "rust-std.txt")))
    return [std, *out]


def _go_string(data: bytes, pos: int) -> tuple[bytes, int]:
    n = shift = 0
    while True:
        b = data[pos]
        pos += 1
        n |= (b & 0x7F) << shift
        shift += 7
        if b < 0x80:
            return data[pos : pos + n], pos + n


def go_components(binary: Path) -> list[Component]:
    """Modules compiled into the ollama binary, read from the build info Go embeds in it."""
    data = binary.read_bytes()
    at = data.find(GO_BUILDINFO)
    while at != -1 and at % 16:
        at = data.find(GO_BUILDINFO, at + 1)
    # Flag 2: version and module list inline, the layout of every Go since 1.18.
    if at == -1 or not data[at + 15] & 2:
        raise NoticeError(f"{binary}: no Go build info, so its modules cannot be listed")
    version, pos = _go_string(data, at + 32)
    modinfo, _ = _go_string(data, pos)
    go_version = version.decode().removeprefix("go")
    std = Component("go", "Go standard library", go_version, "BSD-3-Clause")
    std.texts.append(("upstream go-stdlib.txt", _read_text(VENDORED_DIR / "go" / "go-stdlib.txt")))
    out = [std]
    for line in modinfo[16:-16].decode().splitlines():
        fields = line.split("\t")
        # A replaced module is listed twice; the "=>" line is the code that was built.
        if fields[0] == "=>":
            out.pop()
        if fields[0] in ("dep", "=>"):
            out.append(Component("go", fields[1], fields[2], "see text"))
    return out


def llama_cpp_components() -> list[Component]:
    """Libraries llama.cpp vendors into llama-server, at the tag Ollama pins (stage_payload.sh)."""
    table = json.loads((VENDORED_DIR / "llama.cpp" / "components.json").read_text(encoding="utf-8"))
    out = []
    for name, entry in table["components"].items():
        c = Component("native", name, f"llama.cpp {table['tag']}", entry["licence"])
        text = _read_text(VENDORED_DIR / "llama.cpp" / entry["file"])
        c.texts.append((f"upstream {entry['file']}", text))
        out.append(c)
    return out


def runtime_components(build_file: Path) -> list[Component]:
    """Libraries python-build-standalone links into CPython, which ship no notice of their own."""
    table = json.loads(
        (VENDORED_DIR / "python-build-standalone" / "pbs.json").read_text(encoding="utf-8")
    )
    build = build_file.read_text(encoding="utf-8").strip() if build_file.exists() else "absent"
    python = ".".join(map(str, sys.version_info[:3]))
    if (build, python) != (table["build"], table["python"]):
        raise NoticeError(
            f"the staged runtime is CPython {python} build {build}, the vendored notices are for "
            f"{table['python']} build {table['build']}; re-vendor python-build-standalone/ from "
            "the new build's full archive (docs/desktop-bundle.md, Licence notices)"
        )
    out = []
    for file, entry in table["platforms"][sys.platform].items():
        # Staging prunes some modules (tkinter on macOS); their libraries do not ship.
        if not any(importlib.util.find_spec(m) for m in entry["modules"]):
            continue
        lib = file.removeprefix("LICENSE.").removesuffix(".txt")
        c = Component("runtime", f"{lib} (in {', '.join(entry['modules'])})", "", entry["licence"])
        text = _read_text(VENDORED_DIR / "python-build-standalone" / file)
        c.texts.append((f"python-build-standalone {build} {file}", text))
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


def render(components: list[Component], runtime: list[Component], version: str) -> str:
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
    everything = [*runtime, *components]
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
    ap.add_argument("--runtime-build", type=Path, required=True, help="the runtime's BUILD file")
    ap.add_argument("--npm-root", type=Path, required=True)
    ap.add_argument("--cargo-manifest", type=Path, required=True)
    ap.add_argument("--ollama", type=Path, required=True, help="the staged ollama binary")
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--check", action="store_true", help="fail if --out differs from the stage")
    args = ap.parse_args()

    try:
        runtime_libs = runtime_components(args.runtime_build)
        components = (
            python_components(args.site)
            + npm_components(args.npm_root)
            + cargo_components(_cargo_metadata(args.cargo_manifest))
            + go_components(args.ollama)
            + llama_cpp_components()
        )
    except NoticeError as e:
        print(e, file=sys.stderr)
        return 1
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
    notices = render(components, [runtime, *runtime_libs], args.version)

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
