"""Fetching a large component archive: resumable, verified, never half-applied.

`Range` to resume, sha256 checked before anything is unpacked, and the unpack moved
into place only once complete. The digest is pinned by the build, never fetched
beside the download: whoever serves a bad archive can serve a matching checksum.
"""

import asyncio
import hashlib
import logging
import shutil
import tarfile
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_CHUNK = 1024 * 1024

# A stall is caught by the read timeout; no overall deadline for a 1.4GB transfer.
_TIMEOUT = httpx.Timeout(connect=30.0, read=120.0, write=60.0, pool=30.0)


def sha256_of(path: Path) -> str:
    """Blocking; call through `asyncio.to_thread`."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


async def download_verified(
    url: str,
    sha256: str,
    dest: Path,
    *,
    total_bytes: int = 0,
    label: str = "",
) -> AsyncIterator[dict]:
    """Fetch `url` to `dest` via a `.part` file, resuming and verifying it."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    if dest.is_file() and await asyncio.to_thread(sha256_of, dest) == sha256:
        yield {
            "state": "downloading",
            "detail": f"{label} already downloaded",
            "completed_bytes": total_bytes,
            "total_bytes": total_bytes,
        }
        return

    have = part.stat().st_size if part.is_file() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code == 416:
                # The part is at or past the full length: a corrupt leftover.
                part.unlink(missing_ok=True)
                yield {"state": "failed", "detail": "the partial download was unusable; try again"}
                return
            if resp.status_code not in (200, 206):
                body = (await resp.aread()).decode(errors="replace")[:200]
                yield {"state": "failed", "detail": f"{resp.status_code}: {body}"}
                return

            # A server that ignores Range answers 200 with the whole file.
            resuming = resp.status_code == 206
            if have and not resuming:
                logger.info("range ignored for %s; restarting the download", url)
                have = 0

            total = total_bytes
            if declared := resp.headers.get("Content-Length"):
                total = int(declared) + (have if resuming else 0)

            mode = "ab" if resuming and have else "wb"
            done = have if resuming else 0
            with part.open(mode) as handle:
                async for chunk in resp.aiter_bytes(_CHUNK):
                    await asyncio.to_thread(handle.write, chunk)
                    done += len(chunk)
                    yield {
                        "state": "downloading",
                        "detail": label,
                        "completed_bytes": done,
                        "total_bytes": total,
                    }

    actual = await asyncio.to_thread(sha256_of, part)
    if actual != sha256:
        # Never kept, or the next attempt resumes onto bad bytes forever.
        part.unlink(missing_ok=True)
        yield {
            "state": "failed",
            "detail": (
                "the download did not match its checksum "
                f"(expected {sha256[:12]}, got {actual[:12]})"
            ),
        }
        return

    part.replace(dest)
    yield {
        "state": "downloading",
        "detail": f"{label} verified",
        "completed_bytes": done,
        "total_bytes": total,
    }


def _target_in(into: Path, relative: str) -> Path:
    """Resolve `relative` under `into`, refusing `../` or absolute escapes."""
    root = into.resolve()
    target = (root / relative).resolve()
    if target != root and not target.is_relative_to(root):
        raise ValueError(f"archive member escapes the extraction directory: {relative}")
    return target


def _write(target: Path, reader, mode: int | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        shutil.copyfileobj(reader, handle, _CHUNK)
    if mode is not None:
        target.chmod(mode)


def extract_prefix(archive: Path, member_prefix: str, into: Path) -> int:
    """Extract the members under `member_prefix`, stripping it. Blocking.

    Returns the files written; the caller treats zero as a prefix that stopped matching.
    """
    into.mkdir(parents=True, exist_ok=True)
    written = 0

    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                if info.is_dir() or not info.filename.startswith(member_prefix):
                    continue
                target = _target_in(into, info.filename[len(member_prefix) :])
                with bundle.open(info) as reader:
                    _write(target, reader)
                written += 1
        return written

    # "r|": a zstd reader is not seekable.
    import zstandard  # noqa: PLC0415

    decompressor = zstandard.ZstdDecompressor()
    # Deferred: a symlink is stored before its target, which the copy fallback needs.
    links: list[tuple[Path, str]] = []
    with archive.open("rb") as raw, decompressor.stream_reader(raw) as stream:
        with tarfile.open(fileobj=stream, mode="r|") as bundle:
            for member in bundle:
                if not member.name.startswith(member_prefix):
                    continue
                relative = member.name[len(member_prefix) :]
                if not relative or member.isdir():
                    continue
                target = _target_in(into, relative)
                if member.issym():
                    links.append((target, member.linkname))
                    continue
                if not member.isfile():
                    logger.warning("skipped %s in %s (type %r)", member.name, archive, member.type)
                    continue
                reader = bundle.extractfile(member)
                if reader is None:
                    continue
                # A runner without its executable bit does not load.
                _write(target, reader, member.mode & 0o777)
                written += 1

    for target, linkname in links:
        # The CUDA runner is mostly these soname links; dropping them breaks it.
        # A `../` target is fine as long as it stays inside the extraction root.
        resolved = (target.parent / linkname).resolve()
        if not resolved.is_relative_to(into.resolve()):
            raise ValueError(f"symlink escapes the extraction directory: {linkname}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        try:
            target.symlink_to(linkname)
        except OSError:
            # Windows without developer mode.
            source = target.parent / linkname
            if not source.is_file():
                raise
            shutil.copy2(source, target)
        written += 1
    return written


async def install_archive_subset(
    *,
    url: str,
    sha256: str,
    archive_path: Path,
    member_prefix: str,
    target: Path,
    total_bytes: int,
    label: str,
) -> AsyncIterator[dict]:
    """Download an archive and install one directory out of it, atomically."""
    async for event in download_verified(
        url, sha256, archive_path, total_bytes=total_bytes, label=label
    ):
        yield event
        if event["state"] == "failed":
            return

    yield {
        "state": "downloading",
        "detail": f"Unpacking {label}",
        "completed_bytes": 0,
        "total_bytes": 0,
    }

    staging = target.with_name(f".{target.name}.new")
    await asyncio.to_thread(shutil.rmtree, staging, True)
    try:
        written = await asyncio.to_thread(extract_prefix, archive_path, member_prefix, staging)
    except Exception as exc:
        await asyncio.to_thread(shutil.rmtree, staging, True)
        logger.exception("could not unpack %s", archive_path)
        yield {"state": "failed", "detail": f"could not unpack the download: {exc}"}
        return

    if written == 0:
        await asyncio.to_thread(shutil.rmtree, staging, True)
        yield {
            "state": "failed",
            "detail": f"the archive contained nothing under {member_prefix}",
        }
        return

    await asyncio.to_thread(shutil.rmtree, target, True)
    staging.replace(target)
    await asyncio.to_thread(archive_path.unlink, True)
    yield {"state": "ready", "detail": f"{label} installed ({written} files)"}
