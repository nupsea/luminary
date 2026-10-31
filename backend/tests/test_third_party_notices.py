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


@pytest.fixture
def stage(tmp_path, monkeypatch):
    site, npm, vendored = tmp_path / "site", tmp_path / "web", tmp_path / "vendored"
    site.mkdir()
    npm.mkdir()
    vendored.mkdir()
    (vendored / "vendored.json").write_text(json.dumps({"python": {}, "npm": {}}))
    (vendored / "agpl-3.0.txt").write_text("GNU AFFERO GENERAL PUBLIC LICENSE text")
    runtime = tmp_path / "LICENSE.txt"
    runtime.write_text("PSF licence")
    monkeypatch.setattr(notices, "VENDORED_DIR", vendored)
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
                "--npm-root",
                str(npm),
                "--version",
                "9.9.9",
                "--out",
                str(out),
                *extra,
            ],
        )
        return notices.main()

    return {"site": site, "npm": npm, "vendored": vendored, "out": out, "run": run}


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
