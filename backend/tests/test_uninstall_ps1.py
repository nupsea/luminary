"""scripts/uninstall.ps1 against a fake checkout, with stubs for ollama and uv.

Runs under Windows PowerShell on Windows and pwsh elsewhere. LOCALAPPDATA and
USERPROFILE point into tmp_path, so nothing on the real machine is touched
except in the CI-only tests that exercise the real user environment.
"""

import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
WINDOWS = sys.platform == "win32"
SHELL = shutil.which("powershell") if WINDOWS else shutil.which("pwsh")

pytestmark = pytest.mark.skipif(SHELL is None, reason="no PowerShell on this host")

USER_ENV_LINE = "OPENAI_API_KEY=sk-user-owned"


def _stub(bin_dir: Path, name: str, list_output: str = "") -> None:
    """A command that logs its arguments and prints list_output for `list`."""
    if WINDOWS:
        lines = ["@echo off", f'echo {name} %* >> "%STUB_LOG%"']
        if list_output:
            lines.append('if "%1"=="list" (')
            lines += [f"  echo {line}" for line in list_output.splitlines()]
            lines.append(")")
        (bin_dir / f"{name}.cmd").write_text("\r\n".join(lines) + "\r\n")
    else:
        body = f'echo "{name} $*" >> "$STUB_LOG"\n'
        if list_output:
            body += (
                f'[ "$1" = list ] && printf "{list_output.replace(chr(10), chr(92) + "n")}\\n"\n'
            )
        path = bin_dir / name
        path.write_text(f"#!/bin/sh\n{body}exit 0\n")
        path.chmod(0o755)


def _checkout(tmp_path: Path, manifest: str | None) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    for name in ("uninstall.ps1", "install.ps1"):
        shutil.copy(SCRIPTS / name, repo / "scripts")
    for d in (
        "backend/.venv/Scripts",
        "backend/app/__pycache__",
        "scripts/__pycache__",
        "frontend/node_modules/x",
        "frontend/dist",
        ".luminary",
    ):
        (repo / d).mkdir(parents=True)
    (repo / ".luminary/luminary.db").write_text("library")
    (repo / "start.ps1").write_text("# generated")
    (repo / "backend/.env").write_text(
        f"{USER_ENV_LINE}\nLITELLM_DEFAULT_MODEL=ollama/qwen-test\nVISION_MODEL=ollama/qwen-test\n"
    )
    if manifest is not None:
        (repo / ".install-manifest").write_text(manifest)
    return repo


def _node_home(tmp_path: Path) -> Path:
    return tmp_path / "localappdata/Programs/nodejs"


def _run(tmp_path: Path, repo: Path, *args: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _stub(bin_dir, "ollama", "NAME ID\nqwen-test abc")
    _stub(bin_dir, "uv")
    for d in ("localappdata", "profile"):
        (tmp_path / d).mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    log.touch()
    env = dict(os.environ)
    if WINDOWS:
        root = os.environ["SystemRoot"]
        env["PATH"] = os.pathsep.join(
            [str(bin_dir), rf"{root}\System32", rf"{root}\System32\WindowsPowerShell\v1.0"]
        )
    else:
        env["PATH"] = os.pathsep.join([str(bin_dir), str(Path(SHELL).parent), "/usr/bin", "/bin"])
    env.update(
        LOCALAPPDATA=str(tmp_path / "localappdata"),
        USERPROFILE=str(tmp_path / "profile"),
        STUB_LOG=str(log),
    )
    proc = subprocess.run(
        [
            SHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo / "scripts/uninstall.ps1"),
            *args,
        ],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc, log.read_text()


def test_removes_the_checkout_env_and_only_what_the_manifest_recorded(tmp_path):
    repo = _checkout(tmp_path, "model:qwen-test\nnode:local\n")
    (_node_home(tmp_path)).mkdir(parents=True)
    proc, calls = _run(tmp_path, repo, "-Yes")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    for d in (
        "backend/.venv",
        "backend/app/__pycache__",
        "scripts/__pycache__",
        "frontend/node_modules",
        "frontend/dist",
        "start.ps1",
        ".install-manifest",
    ):
        assert not (repo / d).exists(), d
    env = (repo / "backend/.env").read_bytes()
    assert env.decode().splitlines() == [USER_ENV_LINE]
    assert not env.startswith(b"\xef\xbb\xbf")  # a BOM would glue itself to the first key
    assert (repo / ".luminary/luminary.db").read_text() == "library"
    assert not _node_home(tmp_path).exists()
    assert re.search(r"^ollama rm qwen-test", calls, re.M), calls


def test_without_a_manifest_nothing_global_is_touched_and_leftovers_are_listed(tmp_path):
    repo = _checkout(tmp_path, None)
    (_node_home(tmp_path)).mkdir(parents=True)
    (_node_home(tmp_path) / "node.exe").write_text("")
    proc, calls = _run(tmp_path, repo, "-Yes")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (repo / "backend/.venv").exists()
    assert "ollama rm" not in calls
    assert _node_home(tmp_path).exists()
    by_hand = proc.stdout.split("Not removed:", 1)[1]
    assert "ollama rm qwen-test" in by_hand
    assert str(_node_home(tmp_path)) in by_hand
    assert f'"{tmp_path / "bin"}' in by_hand  # uv by full path: the user's PATH may lack it


def test_recorded_items_are_not_listed_as_leftovers(tmp_path):
    repo = _checkout(tmp_path, "model:qwen-test\nnode:local\nuv\n")
    (_node_home(tmp_path)).mkdir(parents=True)
    (_node_home(tmp_path) / "node.exe").write_text("")
    proc, _ = _run(tmp_path, repo, "-DryRun")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Not removed:" not in proc.stdout


def test_dry_run_lists_the_plan_and_removes_nothing(tmp_path):
    repo = _checkout(tmp_path, "model:qwen-test\n")
    proc, calls = _run(tmp_path, repo, "-DryRun")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Remove backend\\.venv" in proc.stdout
    assert "Remove Ollama model qwen-test" in proc.stdout
    assert (repo / "backend/.venv").exists()
    assert (repo / ".install-manifest").exists()
    assert "ollama rm" not in calls


def test_purge_data_deletes_the_library(tmp_path):
    repo = _checkout(tmp_path, None)
    proc, _ = _run(tmp_path, repo, "-Yes", "-PurgeData")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (repo / ".luminary").exists()


def test_refuses_without_confirmation_when_not_a_terminal(tmp_path):
    repo = _checkout(tmp_path, None)
    proc, _ = _run(tmp_path, repo)

    assert proc.returncode == 1
    assert "pass -Yes" in proc.stdout
    assert (repo / "backend/.venv").exists()


def test_refuses_while_the_backend_is_running(tmp_path):
    repo = _checkout(tmp_path, None)
    with socket.socket() as server:
        try:
            server.bind(("127.0.0.1", 7820))
        except OSError:
            pytest.skip(":7820 is in use on this host")
        server.listen()
        proc, _ = _run(tmp_path, repo, "-Yes")

    assert proc.returncode == 1
    assert "stop Luminary first" in proc.stdout
    assert (repo / "backend/.venv").exists()


def _ps_array(text: str, name: str) -> set[str]:
    found = re.search(rf"^\${name} = @\(([^)]*)\)", text, re.M)
    assert found, name
    return {item.strip().strip('"') for item in found.group(1).split(",")}


def test_uninstall_knows_every_setting_the_installer_writes():
    """A key or user variable install.ps1 writes but uninstall.ps1 does not know
    is left behind as a setting nobody chose."""
    install = (SCRIPTS / "install.ps1").read_text(encoding="utf-8")
    uninstall = (SCRIPTS / "uninstall.ps1").read_text(encoding="utf-8")
    env_keys = set(re.findall(r'^\$EnvLines = Set-EnvLine \$EnvLines "(\w+)"', install, re.M))
    user_env = set(re.findall(r'^Set-UserEnv "(\w+)"', install, re.M))
    assert env_keys and user_env
    assert env_keys == _ps_array(uninstall, "InstallerEnvKeys")
    assert user_env == _ps_array(uninstall, "InstallerUserEnv")
    # Only Set-UserEnv (which records) and Add-UserPath may write the user environment.
    assert re.findall(r"SetEnvironmentVariable\(\s*\"?\$?(\w+)", install) == ["Name", "Path"]


def test_install_records_every_global_it_installs():
    """uninstall.ps1 removes only what the manifest lists; an install step that
    is not recorded becomes a tool nothing will ever remove."""
    text = (SCRIPTS / "install.ps1").read_text(encoding="utf-8")
    for install_step, record in (
        ("Start-Process -FilePath $pyPath", 'Add-Record "python:$pyVer"'),
        ('Move-Item -Path "$nodeStage\\$nodeDist"', 'Add-Record "node:local"'),
        ("astral.sh/uv/install.ps1", 'Add-Record "uv"'),
        ("$setupProc = Start-Process -FilePath $ollamaPath", 'Add-Record "ollama:app"'),
        ("ollama pull $chatModel\n", 'Add-Record "model:$chatModel"'),
        ("ollama pull $visionModel\n", 'Add-Record "model:$visionModel"'),
    ):
        assert record in text.split(install_step, 1)[1][:1500], (
            f"{install_step!r} is not followed by {record!r}"
        )


# These change the real user environment, so they run only on a CI runner.
real_user_env = pytest.mark.skipif(
    not (WINDOWS and os.environ.get("CI")),
    reason="writes the real user environment; Windows CI only",
)


def _user_env(name: str) -> str | None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            return winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            return None


def _set_user_env(name: str, value: str) -> None:
    subprocess.run(
        [
            SHELL,
            "-NoProfile",
            "-Command",
            f'[Environment]::SetEnvironmentVariable("{name}", "{value}", "User")',
        ],
        check=True,
    )


@real_user_env
def test_user_variables_are_removed_or_restored_and_changed_ones_kept(tmp_path):
    _set_user_env("LUMINARY_TEST_OURS", "30m")
    _set_user_env("LUMINARY_TEST_RESTORE", "30m")
    _set_user_env("LUMINARY_TEST_CHANGED", "user-value")
    repo = _checkout(
        tmp_path,
        "env:LUMINARY_TEST_OURS=30m\n"
        "prev:LUMINARY_TEST_RESTORE=-1\nenv:LUMINARY_TEST_RESTORE=30m\n"
        "env:LUMINARY_TEST_CHANGED=30m\n",
    )
    proc, _ = _run(tmp_path, repo, "-Yes")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _user_env("LUMINARY_TEST_OURS") is None
    assert _user_env("LUMINARY_TEST_RESTORE") == "-1"
    assert _user_env("LUMINARY_TEST_CHANGED") == "user-value"
    _set_user_env("LUMINARY_TEST_RESTORE", "")
    _set_user_env("LUMINARY_TEST_CHANGED", "")


@real_user_env
def test_recorded_path_entry_is_removed_and_the_rest_kept_unexpanded(tmp_path):
    import winreg

    ours = str(tmp_path / "luminary-test-bin")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS) as key:
        try:
            original, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            original, kind = "", winreg.REG_EXPAND_SZ
        try:
            winreg.SetValueEx(
                key,
                "Path",
                0,
                winreg.REG_EXPAND_SZ,
                f"{ours};%USERPROFILE%\\luminary-keep;{original}",
            )
            repo = _checkout(tmp_path, f"path:{ours}\n")
            proc, _ = _run(tmp_path, repo, "-Yes")
            after = winreg.QueryValueEx(key, "Path")[0]
        finally:
            winreg.SetValueEx(key, "Path", 0, kind, original)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert ours not in after
    assert after.startswith("%USERPROFILE%\\luminary-keep")
