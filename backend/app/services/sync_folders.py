"""Where an exported library can go: the export folder, and the folders sync services keep.

A sync service (iCloud Drive, Dropbox, Google Drive, OneDrive, Box) moves an archive between
machines like any other file. Only finished archives are ever written into one: a live
library under sync corrupts (WAL and LanceDB files change underneath the client), an archive
is one file that never changes after it appears. Destinations are found again on every call,
and a request names one by id, never by path, so no request can reach any other folder.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.exceptions import NotFound

EXPORTS = "exports"
# In the home folder, not Downloads or Documents: macOS asks before an app writes those.
EXPORT_FOLDER = "Luminary Exports"
# The folder Luminary keeps inside a sync service's.
SYNC_SUBFOLDER = "Luminary"
ARCHIVE_SUFFIX = ".tar.gz"

# Folder-name prefix -> (kind, service). Under ~/Library/CloudStorage a name is
# `<Service>-<account>`; in the home folder it is the service's own.
_SERVICES = (
    ("GoogleDrive", "google-drive", "Google Drive"),
    ("Google Drive", "google-drive", "Google Drive"),
    ("Dropbox", "dropbox", "Dropbox"),
    ("OneDrive", "onedrive", "OneDrive"),
    ("Box", "box", "Box"),
)
# SharePoint sites OneDrive mirrors: their root holds one folder per site, nothing of the user's.
_NOT_A_DRIVE = ("OneDrive-SharedLibraries",)


@dataclass(frozen=True)
class Destination:
    id: str
    kind: str
    name: str
    folder: Path


@dataclass(frozen=True)
class Archive:
    name: str
    bytes: int
    modified: datetime


def destinations() -> list[Destination]:
    """The export folder, then each sync folder on this machine. Blocking: stats the home."""
    home = Path.home()
    found = [Destination(EXPORTS, EXPORTS, EXPORT_FOLDER, home / EXPORT_FOLDER)]
    icloud_folders = (
        home / "Library" / "Mobile Documents" / "com~apple~CloudDocs",
        home / "iCloudDrive",
    )
    for icloud in icloud_folders:
        if icloud.is_dir():
            found.append(Destination(f"icloud:{icloud.name}", "icloud", "iCloud Drive", icloud))
    for parent in (home / "Library" / "CloudStorage", home):
        for entry in _subdirs(parent):
            service = _service(entry)
            if service is not None:
                found.append(service)
    seen: set[Path] = set()
    unique = []
    for dest in found:
        # ~/Dropbox is often a link to ~/Library/CloudStorage/Dropbox.
        key = dest.folder.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(dest)
    return [
        d if d.kind == EXPORTS else Destination(d.id, d.kind, d.name, d.folder / SYNC_SUBFOLDER)
        for d in unique
    ]


def _subdirs(parent: Path) -> list[Path]:
    try:
        return sorted(p for p in parent.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []


def _service(entry: Path) -> Destination | None:
    if entry.name.startswith(_NOT_A_DRIVE):
        return None
    for prefix, kind, service in _SERVICES:
        # Windows names a work OneDrive "OneDrive - <organisation>".
        if entry.name == prefix or entry.name.startswith((f"{prefix}-", f"{prefix} -")):
            account = entry.name[len(prefix) :].strip(" -")
            name = f"{service} ({account})" if account and account != prefix else service
            # Google Drive's root holds only "My Drive" and "Shared drives".
            folder = entry / "My Drive" if (entry / "My Drive").is_dir() else entry
            return Destination(f"{kind}:{entry.name}", kind, name, folder)
    return None


def destination(dest_id: str) -> Destination:
    for dest in destinations():
        if dest.id == dest_id:
            return dest
    raise NotFound(f"No export destination {dest_id!r} on this computer.")


def archives(dest: Destination) -> list[Archive]:
    """The archives in *dest*, newest first. Blocking."""
    found = []
    try:
        entries = list(dest.folder.iterdir())
    except OSError:
        return []
    for path in entries:
        # A dot-name is a transfer still being written, by us or by the sync client.
        if path.name.startswith(".") or not path.name.endswith(ARCHIVE_SUFFIX):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if path.is_file():
            modified = datetime.fromtimestamp(stat.st_mtime, UTC)
            found.append(Archive(path.name, stat.st_size, modified))
    return sorted(found, key=lambda a: a.modified, reverse=True)


def archive_path(dest: Destination, name: str) -> Path:
    """*name*, an archive listed in *dest*; anything else is NotFound."""
    if name not in {a.name for a in archives(dest)}:
        raise NotFound(f"No archive {name!r} in {dest.name}.")
    return dest.folder / name


def reveal(path: Path) -> None:
    """Show *path* selected in the file manager. Blocking."""
    if sys.platform == "darwin":
        argv = ["open", "-R", str(path)]
    elif sys.platform == "win32":
        argv = ["explorer", f"/select,{path}"]
    else:
        argv = ["xdg-open", str(path.parent)]
    # Explorer exits 1 on success; nothing here is worth failing the request over.
    subprocess.run(argv, check=False, timeout=10, capture_output=True)  # noqa: S603 -- argv is fixed, the path a listed archive
