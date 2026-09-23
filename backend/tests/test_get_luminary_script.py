"""scripts/get-luminary.sh against a fake release: file:// assets, no network, no sudo."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "get-luminary.sh"

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="the installer refuses non-Linux hosts"
)

FAKE_APPIMAGE = '#!/bin/sh\n[ "$1" = --appimage-extract ] && exit 1\necho luminary-ran "$@"\n'


def _release(tmp_path: Path, *, checksum: str | None = "real") -> Path:
    assets = tmp_path / "assets"
    assets.mkdir()
    image = assets / "Luminary_9.9.9_amd64.AppImage"
    image.write_text(FAKE_APPIMAGE)
    deb = assets / "Luminary_9.9.9_amd64.deb"
    deb.write_bytes(b"not a deb")
    urls = [image, deb]
    for f in (image, deb):
        if checksum is None:
            continue
        digest = hashlib.sha256(f.read_bytes()).hexdigest() if checksum == "real" else "0" * 64
        sums = assets / f"{f.name}.sha256"
        sums.write_text(f"{digest}  {f.name}\n")
        urls.append(sums)
    body = {"tag_name": "v9.9.9", "assets": [{"browser_download_url": f"file://{u}"} for u in urls]}
    path = tmp_path / "release.json"
    path.write_text(json.dumps(body, indent=2))
    return path


def _run(tmp_path: Path, release: Path, **env: str) -> subprocess.CompletedProcess:
    full_env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "LUMINARY_RELEASE_JSON": str(release),
        "LUMINARY_PREFIX": str(tmp_path / "prefix"),
        "LUMINARY_FORMAT": "appimage",
        "LUMINARY_NO_LAUNCH": "1",
        **env,
    }
    return subprocess.run(
        ["bash", str(SCRIPT)], env=full_env, capture_output=True, text=True, timeout=60
    )


def test_appimage_installs_launcher_and_menu_entry(tmp_path):
    result = _run(tmp_path, _release(tmp_path))
    assert result.returncode == 0, result.stderr
    prefix = tmp_path / "prefix"
    image = prefix / "lib/luminary/Luminary.AppImage"
    assert image.read_text() == FAKE_APPIMAGE
    launcher = prefix / "bin/luminary"
    ran = subprocess.run([str(launcher), "x"], capture_output=True, text=True, check=True)
    assert ran.stdout.strip() == "luminary-ran x"
    entry = (prefix / "share/applications/luminary.desktop").read_text()
    assert f"Exec={launcher}" in entry


def test_checksum_mismatch_refuses_and_installs_nothing(tmp_path):
    result = _run(tmp_path, _release(tmp_path, checksum="wrong"))
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    assert not (tmp_path / "prefix/lib/luminary").exists()


def test_release_without_checksum_is_refused(tmp_path):
    result = _run(tmp_path, _release(tmp_path, checksum=None))
    assert result.returncode != 0
    assert "refusing to install unverified" in result.stderr


def test_unknown_format_is_refused(tmp_path):
    result = _run(tmp_path, _release(tmp_path), LUMINARY_FORMAT="rpm")
    assert result.returncode != 0
    assert "LUMINARY_FORMAT must be" in result.stderr
