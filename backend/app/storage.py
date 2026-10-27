"""Where data lives on disk: one root per library, one for the machine.

A library's database, raw files, images, covers and vectors live under its own root, so
libraries are separated by directory rather than by a column (#388). The default library's
root is `DATA_DIR`, where a desktop install has always kept its data; any other library
lives under `<machine root>/libraries/<id>`. Models, the engine and downloads stay shared.
Code never joins `DATA_DIR` itself; `tests/test_storage_roots.py` fails if it does.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings, get_settings
from app.library import DEFAULT_LIBRARY, current_library, valid_library


def _data_dir(settings: Settings | None) -> Path:
    return Path((settings or get_settings()).DATA_DIR).expanduser()


def library_root(settings: Settings | None = None, library: str | None = None) -> Path:
    """A library's own data: the database, raw files, images, covers, vectors.

    The current library's unless *library* names another.
    """
    library = valid_library(library or current_library())
    if library == DEFAULT_LIBRARY:
        return _data_dir(settings)
    return machine_root(settings) / "libraries" / library


# A library root's folders of files, beside its `luminary.db` and `vectors/`. A snapshot
# carries exactly these; `tests/test_library_snapshot.py` fails on a folder joined elsewhere.
LIBRARY_FILE_DIRS = ("raw", "images", "covers", "notes", "audio", "corpus", "concepts")


def machine_root(settings: Settings | None = None) -> Path:
    """What every library on this machine shares: models, the engine, downloads, reports."""
    return _data_dir(settings)
