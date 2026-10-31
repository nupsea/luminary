"""Re-vendor third_party/python-build-standalone/ for a new runtime build.

    vendor_pbs_licences.py BUILD PYTHON [--archives DIR]

Reads each platform's full archive (the install_only one uv stages carries no library
licences): python/licenses/ for the texts, PYTHON.json for which modules link which.
Needs `zstd` on PATH. Archives already in --archives are not downloaded again.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import tarfile
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "third_party" / "python-build-standalone"
RELEASE = "https://github.com/astral-sh/python-build-standalone/releases/download/{build}/{name}"
# The variants uv installs for the PBS_VERSION platforms in lib.sh.
ARCHIVES = {
    "darwin": "aarch64-apple-darwin-pgo+lto-full",
    "win32": "x86_64-pc-windows-msvc-pgo-full",
    "linux": "x86_64-unknown-linux-gnu-pgo+lto-full",
}
# PYTHON.json names every text a module could need; these corrections are per file.
# Every 3.13 build links OpenSSL 3 (`ssl.OPENSSL_VERSION`), never 1.1.
SKIP = {"LICENSE.cpython.txt", "LICENSE.openssl-1.1.txt"}
LICENCE = {
    "LICENSE.openssl-3.txt": "Apache-2.0",
    "LICENSE.libedit.txt": "BSD-3-Clause",
    "LICENSE.ncurses.txt": "X11",
    "LICENSE.liblzma.txt": "public domain",
    "LICENSE.sqlite.txt": "public domain",
}
# Windows builds these from CPython's own tree, so PYTHON.json lists no licence for them.
WINDOWS_FROM_CPYTHON_TREE = {
    "LICENSE.expat.txt": ("MIT", ["_elementtree", "pyexpat"]),
    "LICENSE.mpdecimal.txt": ("BSD-2-Clause", ["_decimal"]),
    "LICENSE.zlib.txt": ("Zlib", ["zlib"]),
}


def _members(archive: Path) -> tuple[dict, dict[str, bytes]]:
    raw = subprocess.run(  # noqa: S603 -- fixed arguments
        ["zstd", "-dc", str(archive)],  # noqa: S607 -- documented prerequisite
        capture_output=True,
        check=True,
    ).stdout
    meta, texts = {}, {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        for m in tar:
            if m.name == "python/PYTHON.json":
                meta = json.load(tar.extractfile(m))
            elif m.name.startswith("python/licenses/") and m.isfile():
                texts[m.name.rsplit("/", 1)[1]] = tar.extractfile(m).read()
    return meta, texts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("build")
    ap.add_argument("python")
    ap.add_argument("--archives", type=Path, default=Path("build/pbs-full"))
    args = ap.parse_args()
    args.archives.mkdir(parents=True, exist_ok=True)

    table = {"build": args.build, "python": args.python, "platforms": {}}
    texts: dict[str, bytes] = {}
    for platform, variant in ARCHIVES.items():
        name = f"cpython-{args.python}+{args.build}-{variant}.tar.zst"
        archive = args.archives / name
        if not archive.exists():
            url = RELEASE.format(build=args.build, name=name.replace("+", "%2B"))
            urllib.request.urlretrieve(url, archive)  # noqa: S310 -- fixed https URL
        meta, found = _members(archive)
        entries: dict[str, dict] = {}
        for module, variants in meta["build_info"]["extensions"].items():
            for v in variants:
                if v["variant"] != "default":
                    continue
                for path in v.get("license_paths") or []:
                    file = path.rsplit("/", 1)[1]
                    if file in SKIP or file not in found:
                        continue
                    e = entries.setdefault(file, {"licences": set(), "modules": set()})
                    e["licences"].update(v.get("licenses") or [])
                    e["modules"].add(module)
        if platform == "win32":
            for file, (licence, modules) in WINDOWS_FROM_CPYTHON_TREE.items():
                entries[file] = {"licences": {licence}, "modules": set(modules)}
        table["platforms"][platform] = {
            file: {
                "licence": LICENCE.get(file) or " / ".join(sorted(e["licences"])) or "see text",
                "modules": sorted(e["modules"]),
            }
            for file, e in sorted(entries.items())
        }
        for file in entries:
            texts.setdefault(file, found[file])

    for old in OUT.glob("LICENSE.*.txt"):
        old.unlink()
    source = f"https://github.com/astral-sh/python-build-standalone/releases/tag/{args.build}"
    for file, data in texts.items():
        body = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
        header = f"{source} (cpython-{args.python}+{args.build}, python/licenses/{file})\n"
        (OUT / file).write_text(header + body, encoding="utf-8", newline="\n")
    (OUT / "pbs.json").write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")
    print(f"vendored {len(texts)} texts for {args.python}+{args.build}")


if __name__ == "__main__":
    main()
