"""A library's snapshot: one archive of everything under its root, and its restore (#390).

The database is copied through SQLite's backup API, which reads one consistent state while
the app goes on writing. The vector tables are copied as files after their versions are
recorded, and a restore pins each table back to its recorded version. The graph lives in
the database. API keys and the device registry are left out: a snapshot is made to be
moved, and both belong to the machine it was taken on.

A restore goes only into a new library's empty root. The schema revision and embedder are
checked before anything is written, and every file against its hash before the root exists.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from app.database import get_engine, get_session_factory
from app.db_init import known_revision
from app.exceptions import Conflict, InvalidInput
from app.library import DEFAULT_LIBRARY, current_library, use_library, valid_library
from app.paths import app_version
from app.repos.document_repo import DocumentRepo
from app.repos.snapshot_repo import SnapshotCopyRepo
from app.services.model_prefetch import EMBEDDER_REPO
from app.services.settings_service import API_KEY_FIELDS
from app.services.vector_store import EMBEDDING_DIM, get_lancedb_service
from app.storage import LIBRARY_FILE_DIRS, library_root

FORMAT = 1
MANIFEST = "manifest.json"
DATABASE = "luminary.db"
VECTORS = "vectors"
EMBEDDER = {"model": EMBEDDER_REPO, "dim": EMBEDDING_DIM}
_CHUNK = 1 << 20


@dataclass(frozen=True)
class Manifest:
    library: str
    created_at: str
    app_version: str
    schema_revision: str
    embedder: dict[str, Any]
    vector_versions: dict[str, int]
    files: dict[str, dict[str, Any]]
    format: int = FORMAT


async def take_snapshot(dest: Path) -> Manifest:
    """Write the current library's snapshot to *dest*, a new `.tar.gz`."""
    if dest.exists():
        raise Conflict(f"{dest} already exists")
    async with get_session_factory()() as session:
        ingesting = await DocumentRepo(session).ingesting_count()
    if ingesting:
        raise Conflict(
            f"{ingesting} document(s) are still being ingested; snapshot when they finish"
        )
    # Versions first: a vector written after them is dropped on restore, and a note whose
    # vector is missing is embedded again by the note-vector backfill.
    versions = await asyncio.to_thread(get_lancedb_service().table_versions)
    database = Path(get_engine().url.database)
    try:
        return await asyncio.to_thread(
            _write, current_library(), library_root(), database, versions, dest
        )
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def _write(
    library: str, root: Path, database: Path, versions: dict[str, int], dest: Path
) -> Manifest:
    files: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        copy = Path(tmp) / DATABASE
        revision = _backup(database, copy)
        with tarfile.open(dest, "w:gz", compresslevel=1) as tar:
            files[DATABASE] = _add(tar, copy, DATABASE)
            for top in (VECTORS, *LIBRARY_FILE_DIRS):
                for path in sorted((root / top).rglob("*")):
                    if path.is_file():
                        name = path.relative_to(root).as_posix()
                        files[name] = _add(tar, path, name)
            manifest = Manifest(
                library=library,
                created_at=datetime.now(UTC).isoformat(),
                app_version=app_version(),
                schema_revision=revision,
                embedder=EMBEDDER,
                vector_versions=versions,
                files=files,
            )
            body = json.dumps(asdict(manifest), indent=2).encode()
            info = tarfile.TarInfo(MANIFEST)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return manifest


def _backup(source: Path, copy: Path) -> str:
    """Copy the database through the backup API, strip what is the machine's; its revision."""
    # Read-only, so a missing file is an error rather than a new empty database.
    src = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
    dst = sqlite3.connect(copy)
    try:
        src.backup(dst)
        copy_repo = SnapshotCopyRepo(dst)
        copy_repo.strip_machine_rows(API_KEY_FIELDS)
        return copy_repo.schema_revision()
    finally:
        src.close()
        dst.close()


def _add(tar: tarfile.TarFile, path: Path, name: str) -> dict[str, Any]:
    info = tar.gettarinfo(str(path), arcname=name)
    with path.open("rb") as fh:
        reader = _Reader(fh)
        tar.addfile(info, reader)
    return {"bytes": info.size, "sha256": reader.digest.hexdigest()}


class _Reader:
    """A file read through once, hashing what it hands on."""

    def __init__(self, fh: IO[bytes]) -> None:
        self._fh = fh
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self._fh.read(size)
        self.digest.update(data)
        return data


async def restore_snapshot(archive: Path, library: str) -> Manifest:
    """Restore *archive* as *library*, a new library; it migrates to head when next opened."""
    library = valid_library(library)
    if library == DEFAULT_LIBRARY:
        raise InvalidInput("a snapshot restores into a new library, never the default one")
    root = library_root(library=library)
    if root.exists() and any(root.iterdir()):
        raise Conflict(f"library {library!r} already has data at {root}")
    manifest = await asyncio.to_thread(_extract, archive, root)
    with use_library(library):
        await asyncio.to_thread(get_lancedb_service().pin_versions, manifest.vector_versions)
    return manifest


def _extract(archive: Path, root: Path) -> Manifest:
    with tarfile.open(archive, "r:gz") as tar:
        manifest = _check(_read_manifest(tar))
        root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{root.name}-", dir=root.parent))
        try:
            # The data filter refuses absolute paths, links out of the root and devices.
            try:
                tar.extractall(staging, filter="data")
            except tarfile.FilterError as exc:
                raise InvalidInput(f"snapshot holds an unsafe member: {exc}") from exc
            (staging / MANIFEST).unlink()
            _verify(staging, manifest.files)
            staging.chmod(0o700)
            if root.exists():
                root.rmdir()
            staging.rename(root)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return manifest


def _read_manifest(tar: tarfile.TarFile) -> dict[str, Any]:
    try:
        member = tar.extractfile(MANIFEST)
    except KeyError:
        member = None
    if member is None:
        raise InvalidInput("not a library snapshot: no manifest")
    return json.loads(member.read())


def _check(raw: dict[str, Any]) -> Manifest:
    if raw.get("format") != FORMAT:
        raise InvalidInput(f"snapshot format {raw.get('format')!r} is not {FORMAT}")
    try:
        manifest = Manifest(**raw)
    except TypeError as exc:
        raise InvalidInput(f"snapshot manifest is malformed: {exc}") from exc
    if not known_revision(manifest.schema_revision):
        raise InvalidInput(
            f"snapshot schema {manifest.schema_revision} is from a newer version of Luminary "
            f"than {app_version()}"
        )
    # Vectors from another embedder sit in another space; only a re-embed can bring them here.
    if manifest.embedder != EMBEDDER:
        raise InvalidInput(f"snapshot embedder {manifest.embedder} is not {EMBEDDER}")
    return manifest


def _verify(staging: Path, files: dict[str, dict[str, Any]]) -> None:
    found = {p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file()}
    if found != set(files):
        raise InvalidInput(
            f"snapshot files do not match its manifest: {sorted(found ^ set(files))[:5]}"
        )
    for name, expected in files.items():
        digest = hashlib.sha256()
        with (staging / name).open("rb") as fh:
            while chunk := fh.read(_CHUNK):
                digest.update(chunk)
        if digest.hexdigest() != expected["sha256"]:
            raise InvalidInput(f"snapshot file {name} is damaged")
