"""scripts/desktop/third_party_notices.py: no package ships without its licence text (#378)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "third_party_notices",
    Path(__file__).resolve().parents[2] / "scripts" / "desktop" / "third_party_notices.py",
)
notices = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(notices)


def _dist(site: Path, name: str, licence: str, licence_text: str | None) -> None:
    d = site / f"{name}-1.0.dist-info"
    d.mkdir(parents=True)
    (d / "METADATA").write_text(f"Name: {name}\nVersion: 1.0\nLicense-Expression: {licence}\n")
    if licence_text is not None:
        (d / "licenses").mkdir()
        (d / "licenses" / "LICENSE").write_bytes(licence_text.encode())


def _npm(root: Path, packages: dict[str, dict]) -> None:
    lock = {"packages": {"": {}}}
    for path, entry in packages.items():
        lock["packages"][path] = entry.get("lock", {})
        d = root / path
        d.mkdir(parents=True)
        (d / "package.json").write_text(
            json.dumps(
                {"name": path.split("node_modules/")[-1], "version": "1.0", "license": "MIT"}
            )
        )
        if "text" in entry:
            (d / "LICENSE").write_text(entry["text"])
    (root / "package-lock.json").write_text(json.dumps(lock))


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        out.append((n & 0x7F) | (0x80 if n > 0x7F else 0))
        n >>= 7
        if not n:
            return bytes(out)


def _go_binary(path: Path, modules: list[tuple[str, str]]) -> None:
    """A file carrying Go's build info the way the linker lays it out, at a 16-byte boundary."""
    version = b"go1.26.0"
    lines = ["path\tgithub.com/ollama/ollama", "mod\tgithub.com/ollama/ollama\tv1\t"]
    lines += [f"dep\t{m}\t{v}\th1:sum" for m, v in modules]
    modinfo = b"S" * 16 + "\n".join(lines).encode() + b"\n" + b"E" * 16
    header = notices.GO_BUILDINFO + bytes([8, 2]) + bytes(16)
    path.write_bytes(
        bytes(32) + header + _varint(len(version)) + version + _varint(len(modinfo)) + modinfo
    )


def _crate(registry: Path, name: str, licence_text: str | None) -> dict:
    d = registry / f"{name}-1.0"
    d.mkdir(parents=True)
    (d / "Cargo.toml").write_text(f'[package]\nname = "{name}"\n')
    if licence_text is not None:
        (d / "LICENSE-MIT").write_text(licence_text)
    return {
        "id": name,
        "name": name,
        "version": "1.0",
        "license": "MIT",
        "source": "registry+https://github.com/rust-lang/crates.io-index",
        "manifest_path": str(d / "Cargo.toml"),
    }


def _cargo(registry: Path, crates: dict[str, tuple[str | None, str | None]]) -> dict:
    """crates: name -> (licence text, dependency kind from the root: None, "build" or "dev")."""
    root = {"id": "shell", "name": "shell", "version": "1", "source": None, "manifest_path": ""}
    packages = [root] + [_crate(registry, n, text) for n, (text, _) in crates.items()]
    deps = [{"pkg": n, "dep_kinds": [{"kind": kind}]} for n, (_, kind) in crates.items()]
    nodes = [{"id": "shell", "deps": deps}] + [{"id": n, "deps": []} for n in crates]
    return {"packages": packages, "resolve": {"root": "shell", "nodes": nodes}}


@pytest.fixture
def stage(tmp_path, monkeypatch):
    site, npm, vendored = tmp_path / "site", tmp_path / "web", tmp_path / "vendored"
    site.mkdir()
    npm.mkdir()
    for sub in ("cargo", "go", "llama.cpp", "python-build-standalone"):
        (vendored / sub).mkdir(parents=True)
    (vendored / "vendored.json").write_text(
        json.dumps({"python": {}, "npm": {}, "cargo": {}, "go": {}})
    )
    (vendored / "agpl-3.0.txt").write_text("GNU AFFERO GENERAL PUBLIC LICENSE text")
    (vendored / "cargo" / "rust-std.txt").write_text("Rust std text")
    (vendored / "go" / "go-stdlib.txt").write_text("Go std text")
    (vendored / "llama.cpp" / "httplib.txt").write_text("httplib MIT text")
    httplib = {"licence": "MIT", "file": "httplib.txt"}
    (vendored / "llama.cpp" / "components.json").write_text(
        json.dumps({"tag": "b1", "components": {"cpp-httplib": httplib}})
    )
    (vendored / "python-build-standalone" / "LICENSE.openssl-3.txt").write_text("OpenSSL text")
    (vendored / "python-build-standalone" / "LICENSE.tcl.txt").write_text("Tcl text")
    python = ".".join(map(str, sys.version_info[:3]))
    (vendored / "python-build-standalone" / "pbs.json").write_text(
        json.dumps(
            {
                "build": "20250918",
                "python": python,
                "platforms": {
                    sys.platform: {
                        "LICENSE.openssl-3.txt": {"licence": "Apache-2.0", "modules": ["_ssl"]},
                        "LICENSE.tcl.txt": {"licence": "TCL", "modules": ["_no_such_module"]},
                    }
                },
            }
        )
    )
    runtime = tmp_path / "LICENSE.txt"
    runtime.write_text("PSF licence")
    build = tmp_path / "BUILD"
    build.write_text("20250918")
    ollama = tmp_path / "ollama"
    _go_binary(ollama, [])
    cargo = {"meta": _cargo(tmp_path / "registry", {})}
    monkeypatch.setattr(notices, "VENDORED_DIR", vendored)
    monkeypatch.setattr(notices, "_cargo_metadata", lambda manifest: cargo["meta"])
    out = tmp_path / "THIRD-PARTY-LICENSES.txt"

    def run(*extra):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "third_party_notices.py",
                "--site",
                str(site),
                "--runtime-license",
                str(runtime),
                "--runtime-build",
                str(build),
                "--npm-root",
                str(npm),
                "--cargo-manifest",
                str(tmp_path / "Cargo.toml"),
                "--ollama",
                str(ollama),
                "--version",
                "9.9.9",
                "--out",
                str(out),
                *extra,
            ],
        )
        return notices.main()

    return {
        "site": site,
        "npm": npm,
        "vendored": vendored,
        "out": out,
        "run": run,
        "build": build,
        "ollama": ollama,
        "cargo": cargo,
        "registry": tmp_path / "registry",
    }


def test_a_package_without_a_licence_text_fails_the_stage_and_is_named(stage, capsys):
    _dist(stage["site"], "silent", "MIT", None)
    _npm(stage["npm"], {})

    assert stage["run"]() == 1
    assert "python silent 1.0" in capsys.readouterr().err
    assert not stage["out"].exists()


def test_a_vendored_upstream_text_satisfies_a_package_that_ships_none(stage):
    _dist(stage["site"], "silent", "MIT", None)
    _npm(stage["npm"], {"node_modules/@scope/a": {}})
    (stage["vendored"] / "upstream.txt").write_text("Upstream MIT text")
    (stage["vendored"] / "vendored.json").write_text(
        json.dumps({"python": {"silent": "upstream.txt"}, "npm": {"@scope/*": "upstream.txt"}})
    )

    assert stage["run"]() == 0
    text = stage["out"].read_text()
    assert "Upstream MIT text" in text
    assert "same text as silent 1.0" in text


def test_an_agpl_package_makes_the_distribution_agpl_and_ships_the_licence_text(stage):
    _dist(stage["site"], "pymupdf", "AGPL-3.0", "Dual Licensed - GNU AFFERO GPL 3.0")
    _dist(stage["site"], "plain", "MIT", "MIT text")
    _npm(stage["npm"], {})

    assert stage["run"]() == 0
    text = stage["out"].read_text()
    assert "contains pymupdf, licensed under the GNU Affero" in text
    assert "GNU AFFERO GENERAL PUBLIC LICENSE text" in text
    assert "https://github.com/nupsea/luminary/tree/v9.9.9" in text


def test_without_an_agpl_package_no_agpl_statement_is_made(stage):
    _dist(stage["site"], "plain", "MIT", "MIT text")
    _npm(stage["npm"], {})

    assert stage["run"]() == 0
    assert "Affero" not in stage["out"].read_text()


def test_npm_skips_dev_and_native_packages_and_reads_vendored_subtrees(stage):
    _npm(
        stage["npm"],
        {
            "node_modules/tool": {"lock": {"dev": True}},
            "node_modules/canvas-darwin-arm64": {"lock": {"os": ["darwin"], "cpu": ["arm64"]}},
            "node_modules/bundle": {"text": "bundle MIT"},
        },
    )
    vendored = stage["npm"] / "node_modules" / "bundle" / "lib-vendor" / "d3"
    vendored.mkdir(parents=True)
    (vendored / "LICENSE").write_text("d3 ISC text")
    (vendored / "license.js").write_text("module.exports = 'not a notice'")

    assert stage["run"]() == 0
    text = stage["out"].read_text()
    assert "d3 ISC text" in text
    assert "not a notice" not in text
    assert "tool 1.0" not in text and "canvas-darwin-arm64" not in text


def test_check_passes_on_its_own_output_and_fails_once_the_stage_changes(stage):
    _dist(stage["site"], "crlf", "MIT", "line one\r\nline two\r\n")
    _npm(stage["npm"], {})
    assert stage["run"]() == 0
    assert stage["run"]("--check") == 0

    _dist(stage["site"], "added-later", "MIT", "MIT text")
    assert stage["run"]("--check") == 1


def _vendor(stage, ecosystem: str, name: str, text: str) -> None:
    table = json.loads((stage["vendored"] / "vendored.json").read_text())
    (stage["vendored"] / f"{ecosystem}-{len(table[ecosystem])}.txt").write_text(text)
    table[ecosystem][name] = f"{ecosystem}-{len(table[ecosystem])}.txt"
    (stage["vendored"] / "vendored.json").write_text(json.dumps(table))


def test_only_crates_compiled_into_the_shell_are_listed_and_each_needs_a_text(stage, capsys):
    _npm(stage["npm"], {})
    stage["cargo"]["meta"] = _cargo(
        stage["registry"],
        {
            "shipped": ("shipped MIT text", None),
            "codegen": ("codegen text", "build"),
            "testonly": ("test text", "dev"),
            "bare": (None, None),
        },
    )
    assert stage["run"]() == 1
    assert "cargo bare 1.0" in capsys.readouterr().err

    _vendor(stage, "cargo", "bare", "bare upstream text")
    assert stage["run"]() == 0
    text = stage["out"].read_text()
    assert "shipped MIT text" in text and "bare upstream text" in text and "Rust std text" in text
    assert "codegen" not in text and "testonly" not in text


def test_go_modules_are_read_from_the_ollama_binary_and_each_needs_a_text(stage, capsys):
    _npm(stage["npm"], {})
    _go_binary(stage["ollama"], [("github.com/gin-gonic/gin", "v1.10.0")])
    assert stage["run"]() == 1
    assert "go github.com/gin-gonic/gin v1.10.0" in capsys.readouterr().err

    _vendor(stage, "go", "github.com/gin-gonic/gin", "gin MIT text")
    assert stage["run"]() == 0
    text = stage["out"].read_text()
    assert "gin MIT text" in text and "Go standard library 1.26.0" in text
    assert "httplib MIT text" in text


def test_a_binary_without_go_build_info_fails_rather_than_listing_nothing(stage, capsys):
    _npm(stage["npm"], {})
    stage["ollama"].write_bytes(b"\x7fELF stripped of everything")
    assert stage["run"]() == 1
    assert "no Go build info" in capsys.readouterr().err


def test_a_runtime_from_another_build_fails_until_its_libraries_are_re_vendored(stage, capsys):
    _npm(stage["npm"], {})
    assert stage["run"]() == 0
    text = stage["out"].read_text()
    assert "OpenSSL text" in text
    # Its only module is absent from this interpreter, as a pruned one is from the stage.
    assert "Tcl text" not in text

    stage["build"].write_text("20991231")
    assert stage["run"]() == 1
    assert "re-vendor python-build-standalone/" in capsys.readouterr().err
