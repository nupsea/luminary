"""scripts/uninstall.sh and luminary.sh's uv pre-flight, against a fake checkout.

Each test copies the script into a temp repo and puts stubs for ollama, brew and
lsof first on PATH, so nothing on the real machine is touched and every global
removal is observable in a call log.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash scripts")

USER_ENV_LINE = "OPENAI_API_KEY=sk-user-owned"


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f'#!/bin/sh\necho "{name} $*" >> "$STUB_LOG"\n{body}\n')
    path.chmod(0o755)


def _checkout(tmp_path: Path, manifest: str | None) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPTS / "uninstall.sh", repo / "scripts")
    for d in (
        "backend/.venv/bin",
        "backend/app/__pycache__",
        "backend/.pytest_cache",
        "scripts/__pycache__",
        "frontend/node_modules/x",
        "frontend/dist",
        ".luminary",
    ):
        (repo / d).mkdir(parents=True)
    (repo / ".luminary/luminary.db").write_text("library")
    (repo / "backend/.coverage").write_text("coverage")
    (repo / "backend/.env").write_text(
        f"{USER_ENV_LINE}\nLITELLM_DEFAULT_MODEL=ollama/qwen3.5:4b\nVISION_MODEL=ollama/qwen3.5:4b\n"
    )
    if manifest is not None:
        (repo / ".install-manifest").write_text(manifest)
    return repo


def _run(tmp_path: Path, repo: Path, *args: str, listening: bool = False, stdin=subprocess.DEVNULL):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _stub(bin_dir, "ollama", '[ "$1" = list ] && printf "NAME ID\\nqwen-test abc\\n"; exit 0')
    _stub(bin_dir, "brew", "exit 0")
    _stub(bin_dir, "lsof", "exit 0" if listening else "exit 1")
    _stub(bin_dir, "uv", 'echo "$HOME/uv"')
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    log.touch()
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(home), "STUB_LOG": str(log)}
    proc = subprocess.run(
        ["bash", str(repo / "scripts/uninstall.sh"), *args],
        env=env,
        stdin=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc, log.read_text()


def test_removes_the_checkout_env_and_only_what_the_manifest_recorded(tmp_path):
    repo = _checkout(tmp_path, "model:qwen-test\nnode:brew\ntest-models\n")
    test_models = tmp_path / "home/.cache/luminary/test-models"
    (test_models / "bge-small").mkdir(parents=True)
    proc, calls = _run(tmp_path, repo, "--yes")

    assert proc.returncode == 0, proc.stderr
    for d in (
        "backend/.venv",
        "backend/app/__pycache__",
        "backend/.pytest_cache",
        "backend/.coverage",
        "scripts/__pycache__",
        "frontend/node_modules",
        "frontend/dist",
        ".install-manifest",
    ):
        assert not (repo / d).exists(), d
    assert (repo / "backend/.env").read_text() == f"{USER_ENV_LINE}\n"
    assert (repo / ".luminary/luminary.db").read_text() == "library"
    assert not test_models.exists()
    assert "ollama rm qwen-test" in calls
    assert "brew uninstall node" in calls
    assert "brew uninstall ollama" not in calls  # not recorded, so not ours


def test_without_a_manifest_no_global_tool_is_touched(tmp_path):
    repo = _checkout(tmp_path, None)
    proc, calls = _run(tmp_path, repo, "--yes")

    assert proc.returncode == 0, proc.stderr
    assert not (repo / "backend/.venv").exists()
    assert not re.search(r"^(ollama rm|brew (uninstall|services))", calls, re.M), calls


def test_unrecorded_leftovers_are_listed_for_the_user_not_removed(tmp_path):
    repo = _checkout(tmp_path, None)
    (repo / "backend/.env").write_text("LITELLM_DEFAULT_MODEL=ollama/qwen-test\n")
    test_models = tmp_path / "home/.cache/luminary/test-models"
    (test_models / "bge-small").mkdir(parents=True)
    proc, calls = _run(tmp_path, repo, "--yes")

    assert proc.returncode == 0, proc.stderr
    by_hand = proc.stdout.split("Not removed:", 1)[1]
    assert "ollama rm qwen-test" in by_hand
    assert "brew uninstall node" in by_hand
    assert f"rm -rf {test_models}" in by_hand
    assert f"{tmp_path}/bin/uv cache clean" in by_hand  # full path: the user's PATH may lack uv
    assert test_models.exists()
    assert not re.search(r"^(ollama rm|brew (uninstall|services))", calls, re.M), calls


def test_recorded_items_are_not_listed_as_leftovers(tmp_path):
    repo = _checkout(tmp_path, "model:qwen-test\nnode:brew\n")
    (repo / "backend/.env").write_text("LITELLM_DEFAULT_MODEL=ollama/qwen-test\n")
    proc, _ = _run(tmp_path, repo, "--dry-run")

    assert proc.returncode == 0, proc.stderr
    by_hand = proc.stdout.split("Not removed:", 1)[1]
    assert "qwen-test" not in by_hand
    assert "brew uninstall node" not in by_hand


def test_dry_run_lists_the_plan_and_removes_nothing(tmp_path):
    repo = _checkout(tmp_path, "model:qwen-test\n")
    proc, calls = _run(tmp_path, repo, "--dry-run")

    assert proc.returncode == 0, proc.stderr
    assert "Remove backend/.venv" in proc.stdout
    assert "Remove Ollama model qwen-test" in proc.stdout
    assert (repo / "backend/.venv").exists()
    assert (repo / ".install-manifest").exists()
    assert "ollama rm" not in calls


def test_purge_data_deletes_the_library(tmp_path):
    repo = _checkout(tmp_path, None)
    proc, _ = _run(tmp_path, repo, "--yes", "--purge-data")

    assert proc.returncode == 0, proc.stderr
    assert not (repo / ".luminary").exists()


def test_refuses_without_confirmation_when_not_a_terminal(tmp_path):
    repo = _checkout(tmp_path, None)
    proc, _ = _run(tmp_path, repo)

    assert proc.returncode == 1
    assert "pass --yes" in proc.stderr
    assert (repo / "backend/.venv").exists()


def test_refuses_while_the_backend_is_running(tmp_path):
    repo = _checkout(tmp_path, None)
    proc, _ = _run(tmp_path, repo, "--yes", listening=True)

    assert proc.returncode == 1
    assert "stop Luminary first" in proc.stderr
    assert (repo / "backend/.venv").exists()


def test_uninstall_strips_every_key_the_installer_writes():
    """A key install.sh adds to backend/.env but uninstall.sh does not know
    would be left behind as a setting nobody chose."""
    written = set(re.findall(r"^_upsert_env (\w+)", (SCRIPTS / "install.sh").read_text(), re.M))
    listed = re.search(
        r'^INSTALLER_ENV_KEYS="([^"]+)"', (SCRIPTS / "uninstall.sh").read_text(), re.M
    )
    assert written and listed
    assert written == set(listed.group(1).split())


def test_install_records_every_global_it_installs():
    """uninstall.sh removes only what the manifest lists; an install step that
    is not recorded becomes a tool nothing will ever remove."""
    text = (SCRIPTS / "install.sh").read_text()
    for install_cmd, record in (
        ("brew install node", "_record node:brew"),
        ("brew install ollama", "_record ollama:brew"),
        ("_install_node_linux || exit 1", "_record node:local"),
        ("ollama pull", '_record "model:'),
        ("astral.sh/uv/install.sh", "_record uv"),
    ):
        after = text.split(install_cmd, 1)[1]
        assert record in after.split("\n\n", 1)[0], f"{install_cmd!r} is not followed by {record!r}"


def test_launcher_stops_before_touching_ports_when_uv_is_missing(tmp_path):
    """The failure this guards: uv missing, the backend never started, and the
    launcher still printed "Luminary is ready" over a dead API."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    for name in ("luminary.sh", "free_port.sh"):
        shutil.copy(SCRIPTS / name, repo / "scripts")
    fe = repo / "frontend"
    (fe / "node_modules").mkdir(parents=True)
    (fe / "package.json").write_text("{}")
    (fe / "package-lock.json").write_text("{}")
    lock = fe / "node_modules/.package-lock.json"
    lock.write_text("{}")
    os.utime(lock, (os.path.getmtime(fe / "package.json") + 10,) * 2)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    log.touch()
    for tool in ("lsof", "npm", "docker"):
        _stub(bin_dir, tool, "exit 1")
    home = tmp_path / "home"
    home.mkdir()
    proc = subprocess.run(
        ["bash", str(repo / "scripts/luminary.sh")],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(home), "STUB_LOG": str(log)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    if shutil.which("uv", path="/usr/bin:/bin"):
        pytest.skip("uv is installed system-wide on this host")
    assert proc.returncode == 1
    assert "uv not found" in proc.stderr
    assert "make install-dev" in proc.stderr
    assert "ready" not in proc.stdout
    assert log.read_text() == ""  # no lsof, no npm: nothing started or freed
