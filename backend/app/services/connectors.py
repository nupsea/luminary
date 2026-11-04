"""Installed connectors: each in an environment of its own under the machine root.

`<machine root>/connectors/<name>/` holds `env/` (the connector's Python environment, made by
`uv sync` from its own project), `connector.json` (what `describe` returned) and, once the user
signs in, `credentials.json`. Nothing here imports a connector: it runs only as a process
(`connector_runner`).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any

from app.exceptions import DependencyUnavailable, InvalidInput
from app.services.components import resolve_tool
from app.services.connector_runner import InstalledConnector, call
from app.storage import machine_root

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "luminary.connectors"
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_RECORD = "connector.json"
_CREDENTIALS = "credentials.json"
_INSTALL_TIMEOUT_S = 15 * 60


class ConnectorInstallFailed(InvalidInput):
    """The folder is not an installable connector, or its environment would not build."""


def connectors_root() -> Path:
    return machine_root() / "connectors"


def _env_python(env: Path) -> Path:
    return env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _entry_point(folder: Path) -> tuple[str, str]:
    """The one `luminary.connectors` entry point `pyproject.toml` declares, as (name, target)."""
    pyproject = folder / "pyproject.toml"
    if not pyproject.is_file():
        raise ConnectorInstallFailed(f"{folder} has no pyproject.toml")
    try:
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
    except tomllib.TOMLDecodeError as exc:
        raise ConnectorInstallFailed(f"pyproject.toml is not valid TOML: {exc}") from exc
    entries = project.get("entry-points", {}).get(ENTRY_POINT_GROUP, {})
    if len(entries) != 1:
        raise ConnectorInstallFailed(
            f'pyproject.toml must declare exactly one [project.entry-points."{ENTRY_POINT_GROUP}"]'
            f" entry; it declares {len(entries)}"
        )
    ((name, target),) = entries.items()
    if not _NAME.match(name):
        raise ConnectorInstallFailed(
            f"connector name {name!r} must be lower-case letters, digits, -"
        )
    return name, str(target)


def _check_description(name: str, description: dict[str, Any]) -> None:
    if description.get("name") != name:
        raise ConnectorInstallFailed(
            f"describe names the connector {description.get('name')!r}, its entry point {name!r}"
        )
    terms = description.get("terms") or {}
    if not (terms.get("statement") and str(terms.get("url", "")).startswith("https://")):
        raise ConnectorInstallFailed(f"{name} does not state its source's terms and where they are")
    for prefix in description.get("url_prefixes") or []:
        if not re.match(r"^https?://[^/\s]+/", str(prefix)):
            raise ConnectorInstallFailed(f"{name} claims {prefix!r}, which is not a URL prefix")


async def install_from_folder(folder: Path) -> InstalledConnector:
    """Build the connector's own environment from its project, then record what it describes.

    Re-installing a connector replaces its environment and keeps its credentials.
    """
    folder = folder.resolve()
    name, entry = _entry_point(folder)
    uv = resolve_tool("uv")
    if uv is None:
        raise DependencyUnavailable("Installing a connector needs uv (https://docs.astral.sh/uv/).")
    home = connectors_root() / name
    env = home / "env"
    if env.exists():
        shutil.rmtree(env)
    home.mkdir(parents=True, exist_ok=True)
    await _uv_sync(uv, folder, env)

    probe = InstalledConnector(name=name, python=str(_env_python(env)), entry=entry, description={})
    description = await call(probe, "describe")
    _check_description(name, description)
    installed = InstalledConnector(
        name=name, python=probe.python, entry=entry, description=description
    )
    record = {"name": name, "python": installed.python, "entry": entry, "folder": str(folder),
              "description": description}  # fmt: skip
    (home / _RECORD).write_text(json.dumps(record, indent=2), encoding="utf-8")
    logger.info("Installed connector %s from %s", name, folder)
    return installed


async def _uv_sync(uv: str, folder: Path, env: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        uv, "sync", "--project", str(folder), "--no-dev", "--python", sys.executable,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=os.environ | {"UV_PROJECT_ENVIRONMENT": str(env)},
    )  # fmt: skip
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), _INSTALL_TIMEOUT_S)
    except TimeoutError as exc:
        proc.kill()
        raise ConnectorInstallFailed("building the connector's environment timed out") from exc
    if proc.returncode != 0:
        tail = stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        raise ConnectorInstallFailed("uv sync failed: " + " | ".join(tail))


def installed_connectors() -> list[InstalledConnector]:
    root = connectors_root()
    found: list[InstalledConnector] = []
    for record in sorted(root.glob(f"*/{_RECORD}")) if root.is_dir() else []:
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
            found.append(
                InstalledConnector(
                    name=data["name"],
                    python=data["python"],
                    entry=data["entry"],
                    description=data["description"],
                )
            )
        except (ValueError, KeyError, OSError) as exc:
            logger.warning("Skipping unreadable connector record %s: %s", record, exc)
    return found


def connector_for_url(url: str) -> InstalledConnector | None:
    """The installed connector that claims `url` by prefix; the first by name if several do."""
    for connector in installed_connectors():
        if any(url.startswith(p) for p in connector.description.get("url_prefixes") or []):
            return connector
    return None


def save_credentials(name: str, credentials: dict[str, Any]) -> None:
    """Owner-only, as the O'Reilly cookie file is: these are a login."""
    path = connectors_root() / name / _CREDENTIALS
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(credentials))
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def load_credentials(name: str) -> dict[str, Any]:
    path = connectors_root() / name / _CREDENTIALS
    if path.is_file():
        try:
            return dict(json.loads(path.read_text(encoding="utf-8")))
        except ValueError:
            logger.warning("Unreadable credentials for connector %s", name)
    if name == "oreilly":
        # The cookie file the built-in path saved stays where it is until #467.
        from app.services.oreilly_service import get_oreilly_cookies  # noqa: PLC0415

        cookies = get_oreilly_cookies()
        return {"cookies": cookies} if cookies else {}
    return {}
