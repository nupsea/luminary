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

from app.exceptions import DependencyUnavailable, InvalidInput, LuminaryError, NotFound
from app.services.components import capabilities, resolve_tool
from app.services.connector_runner import InstalledConnector, call
from app.storage import machine_root

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "luminary.connectors"
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_RECORD = "connector.json"
_CREDENTIALS = "credentials.json"
_INSTALL_TIMEOUT_S = 15 * 60
# The bundle kinds and host tools a connector may declare; `luminary_source_sdk.protocol`
# lists the same.
MEDIA = ("text", "audio", "youtube")
TOOLS = ("ffmpeg",)
# `luminary_source_sdk.protocol.PLACEHOLDER_TERMS`: an unfilled template's terms, refused.
PLACEHOLDER_TERMS = "Quote what the source's own terms say about downloading and automated use."
_TRANSCRIBED = {"audio", "youtube"}


class ConnectorInstallFailed(InvalidInput):
    """The folder is not an installable connector, or its environment would not build."""


class ConnectorNotInstalled(NotFound):
    pass


class CredentialsRequired(LuminaryError):
    """The connector needs a sign-in it does not have. `connector` in the body names it, so
    the client opens that connector's connect form."""

    status_code = 401


class CredentialsRefused(LuminaryError):
    status_code = 401


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
    _check_terms(name, description.get("terms") or {})
    for prefix in description.get("url_prefixes") or []:
        if not re.match(r"^https?://[^/\s]+/", str(prefix)):
            raise ConnectorInstallFailed(f"{name} claims {prefix!r}, which is not a URL prefix")
    _check_known(name, "writes", description.get("media") or ["text"], MEDIA)
    _check_known(name, "runs", description.get("tools") or [], TOOLS)


def _check_terms(name: str, terms: dict[str, Any]) -> None:
    statement = str(terms.get("statement") or "").strip()
    if not (statement and str(terms.get("url", "")).startswith("https://")):
        raise ConnectorInstallFailed(f"{name} does not state its source's terms and where they are")
    if statement == PLACEHOLDER_TERMS:
        raise ConnectorInstallFailed(f"{name} still carries the template's placeholder terms")


def _check_known(name: str, verb: str, values: list, known: tuple[str, ...]) -> None:
    for value in values:
        if value not in known:
            raise ConnectorInstallFailed(f"{name} {verb} {value!r}; this Luminary knows {known}")


async def install_from_folder(folder: Path, *, locked: bool = False) -> InstalledConnector:
    """Build the connector's own environment from its project, then record what it describes.

    Re-installing a connector replaces its environment and keeps its credentials. `locked`
    installs exactly the project's `uv.lock`, hashes included, as a catalogue install must.
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
    await _uv_sync(uv, folder, env, locked=locked)

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


async def _uv_sync(uv: str, folder: Path, env: Path, *, locked: bool) -> None:
    proc = await asyncio.create_subprocess_exec(
        uv, "sync", "--project", str(folder), "--no-dev", "--python", sys.executable,
        *(["--locked"] if locked else []),
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


def get_connector(name: str) -> InstalledConnector:
    for connector in installed_connectors():
        if connector.name == name:
            return connector
    raise ConnectorNotInstalled(f"No connector named {name!r} is installed")


def claiming(name: str, url: str) -> InstalledConnector:
    """The connector `name`, which must claim `url`: a route never hands one another's link."""
    connector = get_connector(name)
    if not any(url.startswith(p) for p in connector.description.get("url_prefixes") or []):
        raise InvalidInput(f"{label_of(connector)} does not take {url}")
    return connector


def label_of(connector: InstalledConnector) -> str:
    return str(connector.description.get("label") or connector.name)


def needs_credentials(connector: InstalledConnector) -> bool:
    fields = connector.description.get("credentials") or []
    return any(f.get("required", True) for f in fields)


def is_connected(connector: InstalledConnector) -> bool:
    return bool(load_credentials(connector.name)) or not needs_credentials(connector)


def require_credentials(connector: InstalledConnector) -> dict[str, Any]:
    """The stored credentials, or `CredentialsRequired` when a required sign-in is missing:
    refused before a document exists, never after a fetch fails on it."""
    credentials = load_credentials(connector.name)
    if needs_credentials(connector) and not credentials:
        raise CredentialsRequired(f"Connect {label_of(connector)} first.", connector=connector.name)
    return credentials


async def connect(connector: InstalledConnector, values: dict[str, Any]) -> dict[str, Any]:
    """Check the credentials with the connector itself, then store them; its `Account`."""
    fields = {f["name"] for f in connector.description.get("credentials") or []}
    unknown = set(values) - fields
    if unknown:
        raise InvalidInput(f"{label_of(connector)} takes no field {sorted(unknown)[0]!r}")
    account = await call(connector, "check", credentials=values)
    if not account.get("valid"):
        reason = account.get("message") or "those credentials were not accepted"
        raise CredentialsRefused(f"{label_of(connector)}: {reason}", connector=connector.name)
    save_credentials(connector.name, values)
    return account


def uninstall(name: str) -> None:
    """Remove the connector's environment, source and record. Its sign-in stays, so a reinstall
    is connected; the documents it imported stay readable, since the core holds their bundles."""
    get_connector(name)
    home = connectors_root() / name
    (home / _RECORD).unlink(missing_ok=True)
    for part in ("env", "source"):
        shutil.rmtree(home / part, ignore_errors=True)
    logger.info("Uninstalled connector %s", name)


def delete_credentials(name: str) -> None:
    (connectors_root() / name / _CREDENTIALS).unlink(missing_ok=True)
    if name == "oreilly":
        # The built-in path's cookie file is the same login: disconnecting removes both.
        from app.services.oreilly_service import delete_oreilly_cookies  # noqa: PLC0415

        delete_oreilly_cookies()


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


async def missing_components(connector: InstalledConnector) -> list[str]:
    """Components this install lacks for what the connector declares, checked before a fetch:
    an hour of audio downloaded for a library that cannot transcribe it is a dead end."""
    missing = [t for t in connector.description.get("tools") or [] if resolve_tool(t) is None]
    if _TRANSCRIBED & set(connector.description.get("media") or []):
        audio = (await capabilities())["audio_ingest"]
        missing += [c for c in audio["requires"] if c not in missing]
    return missing


def tool_paths(connector: InstalledConnector) -> dict[str, str]:
    """`input["tools"]` for a fetch: the bundled app's PATH may not reach a tool we found."""
    found = {t: resolve_tool(t) for t in connector.description.get("tools") or []}
    return {t: path for t, path in found.items() if path}
