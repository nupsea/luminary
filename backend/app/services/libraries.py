"""The libraries on this machine: which one the app opens, what each is called, and moving one.

The app's own origin works in one library at a time, the active one, recorded in the machine
root so it survives a restart. A paired device keeps the library it paired into. A library's
name and colour are a setting inside it, so they travel with it. A library moves as its
snapshot (`library_snapshot.py`): exported to one archive, imported as a new library, never
over an existing one.
"""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from app.database import get_session_factory
from app.exceptions import Conflict, Forbidden, InvalidInput, NotFound
from app.library import DEFAULT_LIBRARY, current_library, use_library, valid_library
from app.repos.device_repo import device_registry
from app.repos.library_repo import LibraryContentsRepo
from app.repos.settings_repo import SettingsRepo
from app.services.library_snapshot import (
    DATABASE,
    VECTORS,
    Manifest,
    restore_snapshot,
    take_snapshot,
)
from app.services.sync_folders import Destination
from app.storage import LIBRARY_FILE_DIRS, library_root, machine_root

logger = logging.getLogger(__name__)

ACTIVE_FILE = "active_library.json"
PROFILE_KEY = "library_profile"
# Marks a library removed while this process still had it open; startup deletes it.
REMOVED_MARK = ".removed"
COLORS = ("slate", "blue", "green", "amber", "rose", "violet", "teal", "orange")

# Machine root -> the active library; the same id under another `DATA_DIR` is another library.
_active: dict[Path, str] = {}


@dataclass(frozen=True)
class LibraryInfo:
    id: str
    active: bool
    bytes: int
    name: str | None = None
    color: str | None = None
    contents: dict[str, int] | None = None


def library_id(name: str) -> str:
    try:
        return valid_library(name.strip())
    except ValueError as exc:
        raise InvalidInput(
            "A space id is lower-case letters, digits, '-' and '_', starting with a "
            "letter or digit, at most 63 characters."
        ) from exc


def library_exists(library: str) -> bool:
    if library == DEFAULT_LIBRARY:
        return True
    root = library_root(library=library)
    return (root / DATABASE).is_file() and not (root / REMOVED_MARK).exists()


def require_library(library: str) -> str:
    library = library_id(library)
    if not library_exists(library):
        raise NotFound(f"No space named {library!r} on this computer.")
    return library


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
        raise NotFound(f"No space named {library!r} on this computer.")
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


def _library_ids() -> list[str]:
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
    return ids


async def list_libraries() -> list[LibraryInfo]:
    """Every library on this machine, the default first, with its name and contents."""
    active = active_library()
    found = []
    for library in await asyncio.to_thread(_library_ids):
        size = await asyncio.to_thread(_library_bytes, library_root(library=library))
        with use_library(library):
            try:
                profile = await read_profile()
                counts: dict[str, int] | None = await contents()
            except Exception:
                # A damaged library, or one a newer Luminary wrote, still lists.
                logger.warning("could not read library %r", library, exc_info=True)
                profile, counts = {}, None
        found.append(
            LibraryInfo(
                library,
                library == active,
                size,
                name=profile.get("name"),
                color=profile.get("color"),
                contents=counts,
            )
        )
    return found


def _library_bytes(root: Path) -> int:
    # The default library's root is also the machine's, so count only what a library owns.
    total = sum(p.stat().st_size for p in root.glob(f"{DATABASE}*") if p.is_file())
    for top in (VECTORS, *LIBRARY_FILE_DIRS):
        total += sum(p.stat().st_size for p in (root / top).rglob("*") if p.is_file())
    return total


def check_new_library(library: str) -> None:
    if library == DEFAULT_LIBRARY:
        raise InvalidInput("The default space already exists; choose another name.")
    root = library_root(library=library)
    if (root / REMOVED_MARK).exists():
        raise Conflict(
            f"{library!r} was removed and is deleted when Luminary next starts; "
            "choose another name until then."
        )
    if root.exists() and any(root.iterdir()):
        raise Conflict(f"A space named {library!r} already exists on this computer.")


async def read_profile() -> dict[str, Any]:
    """The current library's name and colour, each None when unset."""
    async with get_session_factory()() as session:
        value = await SettingsRepo(session).get(PROFILE_KEY)
    value = value if isinstance(value, dict) else {}
    name, color = value.get("name"), value.get("color")
    return {
        "name": name.strip() or None if isinstance(name, str) else None,
        "color": color if color in COLORS else None,
    }


async def write_profile(*, name: str | None, color: str | None) -> None:
    """Set the current library's name and colour; None clears one."""
    if color is not None and color not in COLORS:
        raise InvalidInput(f"A space colour is one of {', '.join(COLORS)}.")
    name = (name or "").strip() or None
    async with get_session_factory()() as session:
        await SettingsRepo(session).put(PROFILE_KEY, {"name": name, "color": color})
        await session.commit()


async def contents() -> dict[str, int]:
    async with get_session_factory()() as session:
        return await LibraryContentsRepo(session).counts()


async def export_library(dest: Destination) -> tuple[Path, Manifest]:
    """Write the current library's snapshot into *dest*; its path and manifest.

    Built in the machine root and moved in finished, so a sync client never uploads a
    half-written archive or the database copy a snapshot is taken from.
    """
    try:
        await asyncio.to_thread(dest.folder.mkdir, parents=True, exist_ok=True)
    except PermissionError as exc:
        raise _refused(dest.folder) from exc
    label = _file_label((await read_profile())["name"]) or current_library()
    name = f"luminary-{label}-{datetime.now():%Y%m%d-%H%M%S}.tar.gz"
    target = dest.folder / name
    if target.exists():
        raise Conflict(f"{target} already exists; export again in a moment.")
    staging = machine_root() / "downloads"
    await asyncio.to_thread(staging.mkdir, parents=True, exist_ok=True)
    tmp = staging / f".export-{uuid.uuid4().hex}.tar.gz"
    try:
        manifest = await take_snapshot(tmp)
        await asyncio.to_thread(_move_in, tmp, target)
    except PermissionError as exc:
        raise _refused(dest.folder) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return target, manifest


def _file_label(name: str | None) -> str:
    # Named for what the user calls it: "luminary-default-..." says nothing on the other machine.
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower())[:40].strip("-")


def _move_in(source: Path, target: Path) -> None:
    try:
        os.replace(source, target)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    # Another volume: copied in under a dot-name, which no listing shows, then renamed.
    partial = target.with_name(f".{target.name}.partial")
    try:
        shutil.copyfile(source, partial)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)


def _refused(folder: Path) -> Forbidden:
    return Forbidden(
        f"Luminary may not use {folder}. On macOS, allow it under System Settings > "
        "Privacy & Security > Files and Folders, then try again."
    )


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


async def import_from(archive: Path, library: str) -> Manifest:
    """Restore *archive*, a file in an export destination, as *library*, a new library.

    Read where it lies: every file is checked against the manifest's hash, so an archive the
    sync client has not finished fetching fails the check and leaves nothing behind.
    """
    check_new_library(library)
    try:
        return await restore_snapshot(archive, library)
    except PermissionError as exc:
        raise _refused(archive.parent) from exc


async def settle_imported_name(library: str) -> dict[str, Any]:
    """The imported *library*'s name and colour, its name made distinct from the others'."""
    with use_library(library):
        profile = await read_profile()
    if profile["name"] is None:
        return profile
    others = {i.name for i in await list_libraries() if i.id != library}
    if profile["name"] in others:
        # Imported twice, or beside a library of the same name: two "Office"s are one too many.
        profile["name"] = f"{profile['name'][: 37 - len(library)]} ({library})"
        with use_library(library):
            await write_profile(**profile)
    return profile


async def devices_in(library: str) -> int:
    async with device_registry() as devices:
        return await devices.count_in(library)


async def check_removable(library: str) -> None:
    if library == DEFAULT_LIBRARY:
        raise InvalidInput("The default space cannot be removed.")
    if library == active_library():
        raise Conflict("Open another space before removing this one.")
    if paired := await devices_in(library):
        raise Conflict(
            f"{paired} paired device(s) work in {library!r}; unpair them under Devices first."
        )


def mark_removed(library: str) -> None:
    (library_root(library=library) / REMOVED_MARK).touch()


def delete_library_files(library: str) -> None:
    shutil.rmtree(library_root(library=library))


def purge_removed_libraries() -> list[str]:
    """Delete the libraries removed while the last process had them open. Run at startup."""
    others = machine_root() / "libraries"
    if not others.is_dir():
        return []
    purged = []
    for path in others.iterdir():
        if (path / REMOVED_MARK).exists():
            try:
                shutil.rmtree(path)
            except OSError:
                # Still marked, so still hidden; the next start tries again.
                logger.warning("could not delete removed library %s", path, exc_info=True)
                continue
            purged.append(path.name)
    return purged
