"""scripts/get-luminary.sh against a fake release: file:// assets, no network, no sudo.

The host check reads a fake /dev and /proc through LUMINARY_SYSROOT; the drift
tests hold both one-command installers to host_support and run on any OS.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SCRIPT = SCRIPTS / "get-luminary.sh"
PS1 = SCRIPTS / "get-luminary.ps1"

linux_only = pytest.mark.skipif(
    sys.platform != "linux", reason="the installer refuses non-Linux hosts"
)

FAKE_APPIMAGE = '#!/bin/sh\n[ "$1" = --appimage-extract ] && exit 1\necho luminary-ran "$@"\n'

# A 16 GiB box as Linux reports it: installed RAM minus reservations (I-56).
_16GIB_REPORTED_KB = 16_265_432


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


def _sysroot(
    tmp_path: Path, *, nodes: tuple[str, ...] = ("dev/nvidiactl",), mem_kb: int = _16GIB_REPORTED_KB
) -> Path:
    root = tmp_path / "sysroot"
    for node in nodes:
        (root / node).parent.mkdir(parents=True, exist_ok=True)
        (root / node).touch()
    (root / "proc").mkdir(parents=True, exist_ok=True)
    (root / "proc/meminfo").write_text(f"MemTotal:       {mem_kb} kB\nMemFree:  1 kB\n")
    return root


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
    if "LUMINARY_SYSROOT" not in full_env:
        full_env["LUMINARY_SYSROOT"] = str(_sysroot(tmp_path))
    # A new session has no controlling terminal, so the prompt cannot block.
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
        start_new_session=True,
    )


@linux_only
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


@linux_only
def test_checksum_mismatch_refuses_and_installs_nothing(tmp_path):
    result = _run(tmp_path, _release(tmp_path, checksum="wrong"))
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    assert not (tmp_path / "prefix/lib/luminary").exists()


@linux_only
def test_release_without_checksum_is_refused(tmp_path):
    result = _run(tmp_path, _release(tmp_path, checksum=None))
    assert result.returncode != 0
    assert "refusing to install unverified" in result.stderr


@linux_only
def test_unknown_format_is_refused(tmp_path):
    result = _run(tmp_path, _release(tmp_path), LUMINARY_FORMAT="rpm")
    assert result.returncode != 0
    assert "LUMINARY_FORMAT must be" in result.stderr


@linux_only
@pytest.mark.parametrize(
    "node", ["dev/nvidiactl", "proc/driver/nvidia/version", "dev/nvidia0", "dev/kfd"]
)
def test_a_host_with_an_accelerator_and_16gb_installs(tmp_path, node):
    root = _sysroot(tmp_path, nodes=(node,))
    result = _run(tmp_path, _release(tmp_path), LUMINARY_SYSROOT=str(root))
    assert result.returncode == 0, result.stderr
    assert "isn't supported" not in result.stderr


@linux_only
@pytest.mark.parametrize(
    ("nodes", "mem_kb", "why"),
    [
        ((), _16GIB_REPORTED_KB, "no NVIDIA or AMD graphics card"),
        (("dev/nvidiactl",), 8 * 1024 * 1024, "8GB of memory"),
    ],
)
def test_a_refused_host_is_told_before_the_download(tmp_path, nodes, mem_kb, why):
    from app.host_support import UNSUPPORTED_MESSAGE

    root = _sysroot(tmp_path, nodes=nodes, mem_kb=mem_kb)
    result = _run(tmp_path, _release(tmp_path), LUMINARY_SYSROOT=str(root))
    assert result.returncode != 0
    assert UNSUPPORTED_MESSAGE in result.stderr
    assert why in result.stderr
    assert "LUMINARY_INSTALL_ANYWAY=1" in result.stderr
    assert "Downloading" not in result.stderr
    assert not (tmp_path / "prefix/lib/luminary").exists()


@linux_only
@pytest.mark.parametrize(
    "env", [{"LUMINARY_INSTALL_ANYWAY": "1"}, {"LUMINARY_HOST_SUPPORTED": "True"}]
)
def test_a_refused_host_can_still_install(tmp_path, env):
    root = _sysroot(tmp_path, nodes=())
    result = _run(tmp_path, _release(tmp_path), LUMINARY_SYSROOT=str(root), **env)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "prefix/lib/luminary/Luminary.AppImage").exists()


def _assigned(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    assert match, pattern
    return match.group(1)


def test_both_installers_say_what_the_app_says():
    from app.host_support import UNSUPPORTED_MESSAGE

    sh = _assigned(SCRIPT.read_text(encoding="utf-8"), r'^UNSUPPORTED_MESSAGE="(.+)"$')
    ps1 = _assigned(PS1.read_text(encoding="utf-8"), r'^\$UnsupportedMessage = "(.+)"$')
    assert sh == UNSUPPORTED_MESSAGE
    assert ps1.replace("$([char]0x2014)", "—") == UNSUPPORTED_MESSAGE


def test_both_installers_apply_the_apps_floor_and_device_checks():
    from app.memory_profile import _STANDARD_MIN_RAM_GB

    sh = SCRIPT.read_text(encoding="utf-8")
    ps1 = PS1.read_text(encoding="utf-8")
    host = (SCRIPTS.parent / "backend/app/host_support.py").read_text(encoding="utf-8")
    assert int(_assigned(sh, r"^MIN_RAM_GB=(\d+)$")) == _STANDARD_MIN_RAM_GB
    assert int(_assigned(ps1, r"^\$MinRamGB = (\d+)$")) == _STANDARD_MIN_RAM_GB
    for device in ("/dev/nvidiactl", "/proc/driver/nvidia/version", "/dev/kfd", "nvidia[0-9]*"):
        assert device in sh and device in host, device
    for device in ("nvcuda.dll", "amdhip64.dll", "nvidia-smi", "CUDA_VISIBLE_DEVICES"):
        assert device in ps1 and device in host, device
    assert "CUDA_VISIBLE_DEVICES" in sh
