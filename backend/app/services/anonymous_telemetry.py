"""Privacy-first anonymous telemetry service (TelemetryDeck v2 compatible).

Purely for gaining insights into platform distribution (macOS .dmg, Windows, Linux,
Docker) and installation success without compromising privacy.

Strict privacy guarantees:
1. Zero PII: No usernames, home directories, personal paths, document content,
   queries, or prompt data.
2. Pseudonymized identifier: A locally generated random UUID v4 stored in
   .telemetry_id (never derived from machine hardware, MAC address, or user accounts).
3. Opt-Out Respected: If DO_NOT_TRACK=1, LUMINARY_TELEMETRY_DISABLED=1, or
   LUMINARY_TELEMETRY=0 (or disabled in settings), zero network requests are made.
4. Non-blocking & Resilient: Uses a 2.0s bounded timeout and background tasks;
   failures are silently ignored so startup and offline use are never blocked.
"""

import contextlib
import json
import logging
import os
import platform
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.paths import app_version, is_packaged
from app.services.components import running_in_container

logger = logging.getLogger(__name__)

# In-memory preference override (takes precedence if explicitly set via API)
_in_memory_enabled: bool | None = None
_cached_client_id: str | None = None


def get_telemetry_app_id() -> str:
    """Return active TelemetryDeck app ID, or empty string if not configured."""
    env_id = os.environ.get("LUMINARY_TELEMETRY_APP_ID", "").strip()
    if env_id:
        return env_id
    with contextlib.suppress(Exception):
        app_id_file = get_data_dir() / ".telemetry_app_id"
        if app_id_file.is_file():
            saved = app_id_file.read_text().strip()
            if saved:
                return saved
    return get_settings().TELEMETRY_APP_ID.strip()


def set_telemetry_app_id(app_id: str) -> None:
    """Save TelemetryDeck app ID preference."""
    with contextlib.suppress(Exception):
        app_id_file = get_data_dir() / ".telemetry_app_id"
        clean = app_id.strip()
        if clean:
            app_id_file.write_text(clean)
        elif app_id_file.is_file():
            app_id_file.unlink()


def get_local_telemetry_stats() -> dict[str, Any]:
    """Return aggregated install and usage statistics recorded locally."""
    stats_file = get_data_dir() / ".telemetry_stats.json"
    default_stats: dict[str, Any] = {
        "installs_total": 0,
        "runs_total": 0,
        "by_distribution": {},
        "last_event_at": None,
        "recent_events": [],
    }
    if not stats_file.is_file():
        return default_stats
    try:
        with stats_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return {**default_stats, **data}
    except Exception:
        return default_stats


def record_local_event(
    signal_type: str,
    payload: dict[str, Any] | None = None,
    float_value: float | None = None,
) -> None:
    """Record an anonymous event in the local statistics file."""
    stats = get_local_telemetry_stats()
    dist = (payload or {}).get("distribution") or detect_distribution()
    now_iso = datetime.now(UTC).isoformat()

    if signal_type.startswith("install."):
        stats["installs_total"] = stats.get("installs_total", 0) + 1
        by_dist = stats.get("by_distribution", {})
        by_dist[dist] = by_dist.get(dist, 0) + 1
        stats["by_distribution"] = by_dist
    elif signal_type == "app.start":
        stats["runs_total"] = stats.get("runs_total", 0) + 1

    stats["last_event_at"] = now_iso

    event_record = {
        "type": signal_type,
        "timestamp": now_iso,
        "distribution": dist,
        "status": (payload or {}).get("status", "ok"),
        "duration_seconds": (payload or {}).get("duration_seconds") or float_value,
    }

    recent = stats.get("recent_events", [])
    recent.insert(0, event_record)
    stats["recent_events"] = recent[:50]

    stats_file = get_data_dir() / ".telemetry_stats.json"
    with contextlib.suppress(Exception):
        stats_file.write_text(json.dumps(stats, indent=2))


def _home_dir_str() -> str:
    try:
        return str(Path.home())
    except Exception:
        return ""


def _scrub_value(val: Any) -> Any:
    """Scrub local usernames and paths from telemetry values."""
    if not isinstance(val, str):
        return val
    home = _home_dir_str()
    if home and home in val:
        val = val.replace(home, "~")
    username = os.path.basename(home) if home else ""
    if username and len(username) >= 3 and username in val:
        val = val.replace(username, "<user>")
    return val


def _scrub_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Sanitize all payload fields to ensure no PII escapes."""
    clean: dict[str, Any] = {}
    for k, v in payload.items():
        if isinstance(v, (int, float, bool)):
            clean[k] = v
        elif isinstance(v, str):
            clean[k] = str(_scrub_value(v))
        elif isinstance(v, (list, tuple)):
            clean[k] = [_scrub_value(item) for item in v[:20]]
        elif isinstance(v, dict):
            clean[k] = _scrub_payload(v)
        elif v is None:
            clean[k] = None
        else:
            clean[k] = str(v)
    return clean


def get_data_dir() -> Path:
    """Resolve data directory path."""
    settings = get_settings()
    data_dir = Path(settings.DATA_DIR).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def is_telemetry_opted_out() -> bool:
    """Check whether telemetry is disabled via environment variables or user settings."""
    # 0. Private mode sends nothing off the machine. README states that without
    #    qualification, and a user who chose it did so for exactly this reason --
    #    so it outranks every setting below, including an explicit opt-in.
    #    `get_llm_mode` defaults to "private", so an unloaded cache fails closed.
    with contextlib.suppress(Exception):
        from app.services.settings_service import get_llm_mode  # noqa: PLC0415

        if get_llm_mode() == "private":
            return True

    # 1. Standard DO_NOT_TRACK
    dnt = os.environ.get("DO_NOT_TRACK", "").strip().lower()
    if dnt in ("1", "true", "yes"):
        return True

    # 2. Luminary-specific environment toggles
    disabled_var = os.environ.get("LUMINARY_TELEMETRY_DISABLED", "").strip().lower()
    if disabled_var in ("1", "true", "yes"):
        return True

    telemetry_var = os.environ.get("LUMINARY_TELEMETRY", "").strip().lower()
    if telemetry_var in ("0", "false", "no"):
        return True

    # 3. In-memory runtime override (e.g. from PATCH /settings/telemetry)
    if _in_memory_enabled is not None:
        return not _in_memory_enabled

    # 4. File-based preference in data dir
    with contextlib.suppress(Exception):
        pref_file = get_data_dir() / ".telemetry_opt_out"
        if pref_file.is_file():
            content = pref_file.read_text().strip().lower()
            if content in ("1", "true", "opt_out", "disabled"):
                return True

    # 5. Config default
    return not get_settings().TELEMETRY_ENABLED


def set_telemetry_enabled(enabled: bool) -> None:
    """Enable or disable telemetry dynamically and persist preference."""
    global _in_memory_enabled
    _in_memory_enabled = enabled
    try:
        pref_file = get_data_dir() / ".telemetry_opt_out"
        if not enabled:
            pref_file.write_text("1")
        elif pref_file.is_file():
            pref_file.unlink()
    except Exception as exc:
        logger.debug("Failed to persist telemetry preference: %s", exc)


def get_telemetry_client_id() -> str:
    """Return an anonymous random UUID v4 for the installation.

    Persisted in .telemetry_id in the data directory. Never derived from
    hardware serials, MAC addresses, or user account info.
    """
    global _cached_client_id
    if _cached_client_id:
        return _cached_client_id

    data_dir = get_data_dir()
    id_file = data_dir / ".telemetry_id"
    if id_file.is_file():
        with contextlib.suppress(Exception):
            stored_id = id_file.read_text().strip()
            # Validate it's a valid UUID
            uuid.UUID(stored_id)
            _cached_client_id = stored_id
            return stored_id

    # Generate a fresh random UUID v4
    new_id = str(uuid.uuid4())
    try:
        id_file.write_text(new_id)
        os.chmod(id_file, 0o600)
    except Exception as exc:
        logger.debug("Could not write .telemetry_id: %s", exc)

    _cached_client_id = new_id
    return new_id


def check_and_mark_first_run() -> bool:
    """Check if this is the first run of the app on this system.

    Returns True exactly once on the initial startup.
    """
    data_dir = get_data_dir()
    install_file = data_dir / ".install_id"
    if install_file.is_file():
        return False

    try:
        install_file.write_text(f"{datetime.now(UTC).isoformat()} {app_version()}\n")
        os.chmod(install_file, 0o600)
        return True
    except Exception as exc:
        logger.debug("Could not write .install_id: %s", exc)
        return False


def detect_distribution() -> str:
    """Detect the installation and runtime distribution of Luminary."""
    # Explicit override via environment
    explicit = os.environ.get("LUMINARY_INSTALL_SOURCE", "").strip()
    if explicit:
        return explicit

    # Packaged macOS .app / .dmg bundle
    if is_packaged():
        return "macos_dmg"

    # Docker container
    if running_in_container() or os.environ.get("LUMINARY_CONTAINER") == "1":
        return "docker"

    sys_name = platform.system()
    if sys_name == "Darwin":
        exe_path = sys.executable or ""
        prefix_path = sys.prefix or ""
        in_bootstrap = (
            "Application Support/Luminary" in exe_path
            or "Application Support/Luminary" in prefix_path
        )
        if in_bootstrap:
            return "macos_bootstrap"
        return "macos_source"

    if sys_name == "Windows":
        return "windows_native"

    if sys_name == "Linux":
        release = platform.release().lower()
        if "microsoft" in release or "wsl" in release:
            return "linux_wsl"
        return "linux_source"

    return f"other_{sys_name.lower()}"


def get_platform_metadata() -> dict[str, Any]:
    """Basic non-identifying platform specs."""
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "arch": platform.machine(),
        "python_version": platform.python_version(),
        "luminary_version": app_version(),
        "distribution": detect_distribution(),
    }


async def send_signal(
    signal_type: str,
    payload: dict[str, Any] | None = None,
    float_value: float | None = None,
) -> bool:
    """Send an anonymous signal to TelemetryDeck v2.

    Returns True if sent successfully, False if opted-out or failed.
    Non-blocking, bounded by 2.0s, completely silent on error.
    """
    if is_telemetry_opted_out():
        return False

    app_id = get_telemetry_app_id()
    client_user = get_telemetry_client_id()

    # Merge standard metadata with custom payload
    merged_payload = get_platform_metadata()
    if payload:
        merged_payload.update(payload)

    clean_payload = _scrub_payload(merged_payload)

    # Always record the event in local statistics store
    record_local_event(signal_type, clean_payload, float_value)

    # If TelemetryDeck app ID is not configured, event is saved locally
    if not app_id:
        return True

    # TelemetryDeck v2 format: JSON array of event objects
    body = [
        {
            "appID": app_id,
            "clientUser": client_user,
            "type": signal_type,
            "payload": clean_payload,
        }
    ]
    if float_value is not None:
        body[0]["floatValue"] = float_value

    endpoint = get_settings().TELEMETRY_ENDPOINT.rstrip("/") + "/"

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.post(
                endpoint,
                json=body,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            return 200 <= resp.status_code < 300
    except Exception as exc:
        logger.debug("Anonymous telemetry dispatch skipped: %s", exc)
        return False


async def record_startup_telemetry() -> None:
    """Record startup events: install.first_run on initial run, and app.start."""
    try:
        is_first = check_and_mark_first_run()
        if is_first:
            logger.info("First run detected; dispatching install telemetry")
            await send_signal("install.first_run")

        await send_signal("app.start")
    except Exception as exc:
        logger.debug("Startup telemetry error: %s", exc)


async def fetch_github_release_dmg_downloads(repo: str = "nupsea/luminary") -> dict[str, Any]:
    """Fetch DMG download counts from GitHub Releases API for the repository."""
    url = f"https://api.github.com/repos/{repo}/releases"
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(
                url,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "Luminary-Telemetry/1.0",
                },
            )
            if resp.status_code != 200:
                err_msg = f"GitHub API returned {resp.status_code}"
                return {"error": err_msg, "total_dmg_downloads": 0}

            releases = resp.json()
            total_dmg_downloads = 0
            dmg_assets: list[dict[str, Any]] = []

            for release in releases:
                tag = release.get("tag_name", "unknown")
                for asset in release.get("assets", []):
                    name = asset.get("name", "")
                    if name.endswith(".dmg"):
                        downloads = asset.get("download_count", 0)
                        total_dmg_downloads += downloads
                        dmg_assets.append({
                            "release": tag,
                            "name": name,
                            "downloads": downloads,
                            "created_at": asset.get("created_at"),
                            "updated_at": asset.get("updated_at"),
                        })

            return {
                "total_dmg_downloads": total_dmg_downloads,
                "dmg_assets": dmg_assets,
            }
    except Exception as exc:
        logger.debug("Failed to fetch GitHub DMG download metrics: %s", exc)
        return {"error": str(exc), "total_dmg_downloads": 0}
