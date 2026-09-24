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
    (tmp_path / "home").mkdir(exist_ok=True)
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
    assert "Removing the app keeps it." in result.stdout


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


@linux_only
def test_a_failure_saves_a_report_without_the_home_path(tmp_path):
    result = _run(tmp_path, _release(tmp_path, checksum="wrong"))
    assert result.returncode != 0
    report = (tmp_path / "home/luminary-install-report.txt").read_text()
    assert "Error: checksum mismatch" in report
    assert "==> Downloading" in report
    assert "library ~/.local/share/sh.luminary.app" in report
    assert str(tmp_path / "home") not in report
    assert "eanups@yahoo.com" in result.stderr


@linux_only
def test_a_refusal_saves_no_report(tmp_path):
    result = _run(tmp_path, _release(tmp_path), LUMINARY_FORMAT="rpm")
    assert result.returncode != 0
    assert not (tmp_path / "home/luminary-install-report.txt").exists()


def _library(tmp_path: Path) -> Path:
    data = tmp_path / "home/.local/share/sh.luminary.app"
    for piece in ("luminary.db", "engine/ollama/ollama", "ollama/models/blobs/sha256-x"):
        (data / piece).parent.mkdir(parents=True, exist_ok=True)
        (data / piece).write_text("x")
    logs = tmp_path / "home/.local/state/luminary"
    logs.mkdir(parents=True)
    (logs / "luminary.log").write_text("x")
    return data


@linux_only
def test_uninstall_removes_the_app_and_keeps_the_library(tmp_path):
    release = _release(tmp_path)
    assert _run(tmp_path, release).returncode == 0
    data = _library(tmp_path)

    result = _run(tmp_path, release, LUMINARY_UNINSTALL="1", LUMINARY_ASSUME_YES="1")

    assert result.returncode == 0, result.stderr
    prefix = tmp_path / "prefix"
    assert not (prefix / "lib/luminary").exists()
    assert not (prefix / "bin/luminary").exists()
    assert not (prefix / "share/applications/luminary.desktop").exists()
    assert not (data / "engine").exists()
    assert not (tmp_path / "home/.local/state/luminary").exists()
    assert (data / "luminary.db").exists()
    assert (data / "ollama/models/blobs/sha256-x").exists()
    assert "Your library was kept" in result.stdout
    assert f"It does not touch your library at {data}" in result.stdout
    lines = result.stdout.splitlines()
    assert f"  - the app in {prefix}/lib/luminary" in lines
    assert f"To delete it permanently:   rm -rf {data}" in lines
    assert f"To free only the models:    rm -rf {data}/ollama/models" in lines


@linux_only
def test_uninstall_without_a_terminal_or_consent_removes_nothing(tmp_path):
    release = _release(tmp_path)
    assert _run(tmp_path, release).returncode == 0
    data = _library(tmp_path)

    result = _run(tmp_path, release, LUMINARY_UNINSTALL="1")

    assert result.returncode != 0
    assert "nothing was removed" in result.stderr
    assert "LUMINARY_ASSUME_YES=1" in result.stderr
    assert (tmp_path / "prefix/lib/luminary/Luminary.AppImage").exists()
    assert (data / "engine").exists()
    assert (tmp_path / "home/.local/state/luminary/luminary.log").exists()


@linux_only
def test_uninstall_leaves_files_it_did_not_install(tmp_path):
    release = _release(tmp_path)
    assert _run(tmp_path, release).returncode == 0
    theirs = tmp_path / "prefix/lib/luminary/notes.txt"
    theirs.write_text("mine")
    logs = tmp_path / "home/.local/state/luminary"
    logs.mkdir(parents=True)
    (logs / "luminary.log").write_text("x")
    (logs / "other.txt").write_text("mine")

    result = _run(tmp_path, release, LUMINARY_UNINSTALL="1", LUMINARY_ASSUME_YES="1")

    assert result.returncode == 0, result.stderr
    assert theirs.read_text() == "mine"
    assert not (tmp_path / "prefix/lib/luminary/Luminary.AppImage").exists()
    assert (logs / "other.txt").exists()
    assert not (logs / "luminary.log").exists()
    lines = [line.strip() for line in result.stdout.splitlines()]
    assert f"delete: rm -rf {theirs.parent}" in lines
    assert f"delete: rm -rf {logs}" in lines


@linux_only
def test_uninstall_leaves_a_launcher_it_did_not_write(tmp_path):
    bin_dir = tmp_path / "prefix/bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "luminary").write_text("#!/bin/sh\necho someone else's\n")

    result = _run(tmp_path, _release(tmp_path), LUMINARY_UNINSTALL="1", LUMINARY_ASSUME_YES="1")

    assert result.returncode == 0, result.stderr
    assert (bin_dir / "luminary").exists()


@linux_only
def test_an_older_version_is_not_installed_over_a_newer_one(tmp_path):
    release = _release(tmp_path)
    assert _run(tmp_path, release).returncode == 0
    recorded = tmp_path / "prefix/lib/luminary/VERSION"
    assert recorded.read_text().strip() == "9.9.9"
    recorded.write_text("10.0.0\n")

    refused = _run(tmp_path, release)
    assert refused.returncode != 0
    assert "Luminary 10.0.0 is installed and 9.9.9 is older" in refused.stderr
    assert "Downloading" not in refused.stderr
    assert not (tmp_path / "home/luminary-install-report.txt").exists()

    allowed = _run(tmp_path, release, LUMINARY_ALLOW_DOWNGRADE="1")
    assert allowed.returncode == 0, allowed.stderr
    assert recorded.read_text().strip() == "9.9.9"


def _user_ollama(tmp_path: Path, *, corrupt: bool = False) -> tuple[Path, list[Path]]:
    store = tmp_path / "home/.ollama/models"
    blobs = []
    layers = []
    for body in (b"weights", b"template"):
        digest = hashlib.sha256(body).hexdigest()
        blob = store / f"blobs/sha256-{digest}"
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(b"damaged" if corrupt and body == b"weights" else body)
        blobs.append(blob)
        layers.append({"digest": f"sha256:{digest}", "size": len(body)})
    manifest = store / "manifests/registry.ollama.ai/library/qwen3.5/4b"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"config": layers[1], "layers": layers[:1]}))
    return store, blobs


@linux_only
def test_models_from_the_users_ollama_are_linked_and_theirs_left_alone(tmp_path):
    store, blobs = _user_ollama(tmp_path)
    before = {b: (b.read_bytes(), b.stat().st_mode) for b in blobs}

    result = _run(tmp_path, _release(tmp_path), LUMINARY_REUSE_MODELS="1")

    assert result.returncode == 0, result.stderr
    assert "Found your own Ollama" in result.stdout
    ours = tmp_path / "home/.local/share/sh.luminary.app/ollama/models"
    assert (ours / "manifests/registry.ollama.ai/library/qwen3.5/4b").exists()
    for blob in blobs:
        linked = ours / "blobs" / blob.name
        assert linked.stat().st_ino == blob.stat().st_ino
        assert (blob.read_bytes(), blob.stat().st_mode) == before[blob]
    assert not list(ours.glob("blobs/*.partial"))


@linux_only
def test_a_damaged_model_is_not_reused_and_the_install_still_succeeds(tmp_path):
    _, blobs = _user_ollama(tmp_path, corrupt=True)

    result = _run(tmp_path, _release(tmp_path), LUMINARY_REUSE_MODELS="1")

    assert result.returncode == 0, result.stderr
    assert "does not match its checksum" in result.stderr
    assert all(b.exists() for b in blobs)
    ours = tmp_path / "home/.local/share/sh.luminary.app/ollama/models"
    assert not (ours / "manifests/registry.ollama.ai/library/qwen3.5/4b").exists()
    assert not list(ours.glob("blobs/*"))


@linux_only
def test_models_are_not_reused_without_being_asked(tmp_path):
    _user_ollama(tmp_path)

    result = _run(tmp_path, _release(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "LUMINARY_REUSE_MODELS=1" in result.stdout
    assert not (tmp_path / "home/.local/share/sh.luminary.app").exists()


def test_both_installers_offer_the_models_the_app_knows():
    from app.model_registry import REGISTRY

    known = {key.split("/", 1)[1] for key in REGISTRY if key.startswith("ollama/")}
    sh = _assigned(SCRIPT.read_text(encoding="utf-8"), r'^KNOWN_MODELS="(.+)"$')
    ps1 = _assigned(PS1.read_text(encoding="utf-8"), r'^\$KnownModels = @\((.+)\)$')
    assert set(sh.split()) == known
    assert {m.strip().strip('"') for m in ps1.split(",")} == known


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
