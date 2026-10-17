"""Where data lives on disk: one root for a library's data, one for the machine's.

Both are `DATA_DIR` today. They are separate so a second library (0.17.0) gets its own
root by changing `library_root` alone, while models, the engine and downloads stay shared.
Code never joins `DATA_DIR` itself; `tests/test_storage_roots.py` fails if it does.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings, get_settings


def _data_dir(settings: Settings | None) -> Path:
    return Path((settings or get_settings()).DATA_DIR).expanduser()


def library_root(settings: Settings | None = None) -> Path:
    """The library's own data: the database, raw files, images, covers, vectors."""
    return _data_dir(settings)


def machine_root(settings: Settings | None = None) -> Path:
    """What every library on this machine shares: models, the engine, downloads, reports."""
    return _data_dir(settings)
