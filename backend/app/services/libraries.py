"""Which library the app opens, and moving a library between machines.

The app's own origin works in one library at a time, the active one, recorded in the machine
root so it survives a restart. A paired device keeps the library it paired into. A library
moves as its snapshot (`library_snapshot.py`): exported to one archive, imported as a new
library, never over an existing one.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO

from app.database import get_session_factory
from app.exceptions import Conflict, InvalidInput, NotFound
from app.library import DEFAULT_LIBRARY, current_library, valid_library
from app.repos.library_repo import LibraryContentsRepo
from app.services.library_snapshot import (
    DATABASE,
    VECTORS,
    Manifest,
    restore_snapshot,
    take_snapshot,
)
from app.storage import LIBRARY_FILE_DIRS, library_root, machine_root

logger = logging.getLogger(__name__)

ACTIVE_FILE = "active_library.json"
# In the home folder, not Downloads or Documents: macOS asks before an app writes those.
EXPORT_FOLDER = "Luminary Exports"

# Machine root -> the active library; the same id under another `DATA_DIR` is another library.
_active: dict[Path, str] = {}


@dataclass(frozen=True)
class LibraryInfo:
    id: str
    active: bool
    bytes: int


def library_id(name: str) -> str:
    try:
        return valid_library(name.strip())
    except ValueError as exc:
        raise InvalidInput(
            "A library name is lower-case letters, digits, '-' and '_', starting with a "
            "letter or digit, at most 63 characters."
        ) from exc


def library_exists(library: str) -> bool:
    if library == DEFAULT_LIBRARY:
        return True
    return (library_root(library=library) / DATABASE).is_file()


def active_library() -> str:
    root = machine_root()
    if root not in _active:
        _active[root] = _read_active(root / ACTIVE_FILE)
    return _active[root]


def _read_active(path: Path) -> str:
    try:
        library = valid_library(json.loads(path.read_text())["library"])
    except FileNotFoundError:
        return DEFAULT_LIBRARY
    except (ValueError, KeyError, TypeError):
        logger.warning("%s is unreadable; opening the default library", path)
        return DEFAULT_LIBRARY
    if not library_exists(library):
        logger.warning("active library %r is gone; opening the default library", library)
        return DEFAULT_LIBRARY
    return library


def set_active_library(library: str) -> None:
    if not library_exists(library):
        raise NotFound(f"No library named {library!r} on this machine.")
    root = machine_root()
    # Written beside and renamed over, so a crash leaves the old choice or the new, never half.
    fd, tmp = tempfile.mkstemp(dir=root, prefix=f".{ACTIVE_FILE}.")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump({"library": library}, fh)
        os.replace(tmp, root / ACTIVE_FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _active[root] = library


def list_libraries() -> list[LibraryInfo]:
    """Every library on this machine, the default first. Blocking: walks each root."""
    active = active_library()
    ids = [DEFAULT_LIBRARY]
    others = machine_root() / "libraries"
    if others.is_dir():
        for path in sorted(others.iterdir()):
            # Restore staging folders start with a dot, which no library id can.
            try:
                library = valid_library(path.name)
            except ValueError:
                continue
            if library_exists(library):
                ids.append(library)
    return [LibraryInfo(i, i == active, _library_bytes(library_root(library=i))) for i in ids]


def _library_bytes(root: Path) -> int:
    # The default library's root is also the machine's, so count only what a library owns.
    total = sum(p.stat().st_size for p in root.glob(f"{DATABASE}*") if p.is_file())
    for top in (VECTORS, *LIBRARY_FILE_DIRS):
        total += sum(p.stat().st_size for p in (root / top).rglob("*") if p.is_file())
    return total


def check_new_library(library: str) -> None:
    if library == DEFAULT_LIBRARY:
        raise InvalidInput("The default library already exists; choose another name.")
    root = library_root(library=library)
    if root.exists() and any(root.iterdir()):
        raise Conflict(f"A library named {library!r} already exists on this machine.")


async def contents() -> dict[str, int]:
    async with get_session_factory()() as session:
        return await LibraryContentsRepo(session).counts()


async def export_library() -> tuple[Path, Manifest]:
    """Write the current library's snapshot into the export folder; its path and manifest."""
    folder = Path.home() / EXPORT_FOLDER
    await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
    name = f"luminary-{current_library()}-{datetime.now():%Y%m%d-%H%M%S}.tar.gz"
    dest = folder / name
    if dest.exists():
        raise Conflict(f"{dest} already exists; export again in a moment.")
    # Named to appear only once complete: a sync client never uploads a half-written archive.
    partial = folder / f".{name}.partial"
    manifest = await take_snapshot(partial)
    await asyncio.to_thread(os.replace, partial, dest)
    return dest, manifest


async def import_archive(upload: IO[bytes], library: str) -> Manifest:
    """Restore the uploaded snapshot as *library*, a new library."""
    check_new_library(library)
    downloads = machine_root() / "downloads"
    await asyncio.to_thread(downloads.mkdir, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=downloads, prefix=".import-", suffix=".tar.gz")
    archive = Path(name)
    try:
        with os.fdopen(fd, "wb") as fh:
            await asyncio.to_thread(shutil.copyfileobj, upload, fh, 1 << 20)
        return await restore_snapshot(archive, library)
    finally:
        archive.unlink(missing_ok=True)
