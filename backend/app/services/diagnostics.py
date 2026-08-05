"""The environment block that travels with a bug report.

Requested in nupsea/luminary#41: a version and an OS name were not enough to
rebuild a reporter's setup, so answering an issue always cost a round trip.

Assembled here rather than in the desktop shell because the running app's UI is
served from the backend's own origin, where Tauri IPC is not granted -- and
because a browser or Docker install has no shell to ask.
"""

import os
import platform
import subprocess
from pathlib import Path

import httpx

from app.config import get_settings
from app.paths import app_version, is_packaged
from app.services.settings_service import get_local_chat_model, get_vision_model


def _scrub(text: str) -> str:
    """Paths carry the account name, and this is going onto a public tracker."""
    home = str(Path.home())
    out = text.replace(home, "~")
    user = os.path.basename(home)
    return out.replace(user, "<user>") if len(user) >= 3 else out


def _kernel() -> str:
    u = platform.uname()
    return f"{u.system} {u.release} {u.machine}"


def _os_name() -> str:
    if platform.system() != "Darwin":
        return f"{platform.system()} {platform.release()}"
    try:
        product = subprocess.run(
            ["/usr/bin/sw_vers", "-productVersion"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        build = subprocess.run(
            ["/usr/bin/sw_vers", "-buildVersion"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "macOS (version unavailable)"
    return f"macOS {product} (build {build})"


async def _ollama() -> list[str]:
    url = get_settings().OLLAMA_URL
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            version = (await client.get(f"{url}/api/version")).json().get("version", "unknown")
            tags = (await client.get(f"{url}/api/tags")).json().get("models", [])
    except Exception:
        return ["ollama    not reachable"]

    names = [m.get("name", "") for m in tags if m.get("name")]
    lines = [f"ollama    running — {version}"]
    lines += [f"          {n}" for n in names] or ["          no models installed"]
    return lines


async def environment_report() -> str:
    """A paste-ready block for an issue. Every line is one a maintainer uses."""
    settings = get_settings()
    install = "desktop app" if is_packaged() else "source or CLI install"
    lines = [
        f"version   {app_version()} ({install})",
        f"library   {_scrub(str(Path(settings.DATA_DIR).expanduser()))}",
        f"os        {_os_name()}",
        f"kernel    {_kernel()}",
        f"python    {platform.python_version()}",
        f"mode      {settings.LUMINARY_MODE}",
        f"chat      {get_local_chat_model()}",
        f"vision    {get_vision_model()}",
    ]
    lines += await _ollama()
    return _scrub("\n".join(lines))
