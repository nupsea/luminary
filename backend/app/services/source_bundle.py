"""The one way a source bundle enters the library: copied in entry by entry, then validated.

A bundle is a directory a connector wrote: `manifest.json`, `sections/`, `assets/`. The copy
is checked as it is made, and the manifest is read from the copy, so nothing the connector
changes afterwards reaches the library. `docs/roadmap.md` §7 has the design.
"""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import stat
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from app.exceptions import InvalidInput
from app.schemas.source_bundle import BUNDLE_VERSION, AudioMedia, BundleManifest, YoutubeMedia
from app.types import AUDIO_EXTENSIONS, ParsedDocument, Section

MANIFEST = "manifest.json"
BUNDLE_SUFFIX = ".bundle"
_TOP_LEVEL_DIRS = frozenset({"sections", "assets"})
_SECTION_SUFFIXES = frozenset({".html", ".htm", ".xhtml", ".md"})
_COPY_BLOCK = 1024 * 1024

# Each ceiling admits the first case and exists to refuse the second.
# The largest chapter in four real EPUBs is 194 KB; `_split_epub_document` is quadratic in
# headings, 1.7 s on a 4 MiB file and 25 s on a 16 MiB one.
MAX_SECTION_FILE_BYTES = 4 * 1024**2
# The largest document in the dev library is 810,621 words in 1,017 sections (about 5 MB of
# text); past 64 MiB a connector has fetched far more than one document.
MAX_SECTION_TEXT_BYTES = 64 * 1024**2
# The same manual's 1,017 sections are the most in the dev library; 5,000 table-of-contents
# entries is a whole wiki space crawled into one document, which belongs in several.
MAX_SECTIONS = 5_000
# Thirteen hours of a talk's audio at the 155 MB an hour the dev library's FLAC measures; an
# hour of 1080p video (about 3 GB) is refused, since transcription takes only audio.
MAX_BUNDLE_BYTES = 2 * 1024**3
# A 5,000-section book with three figures a section.
MAX_FILES = 20_000


class BundleRefused(InvalidInput):
    """A bundle the importer will not take. The message names the entry and the rule."""


def store_bundle(
    source: Path, dest: Path, *, media: frozenset[str] = frozenset({"text"})
) -> BundleManifest:
    """Copy the bundle at `source` to `dest`, checking every entry; return its manifest.

    `dest` must not exist. A refused or interrupted copy leaves nothing at `dest`. `media`
    names the kinds this core can ingest.
    """
    if dest.exists():
        raise BundleRefused(f"{dest.name} already exists")
    partial = dest.with_name(f"{dest.name}.partial")
    if partial.exists():
        shutil.rmtree(partial)
    try:
        _copy_checked(source, partial)
        manifest = _admitted(read_manifest(partial), media)
        partial.rename(dest)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return manifest


def _admitted(manifest: BundleManifest, media: frozenset[str]) -> BundleManifest:
    if manifest.media.kind not in media:
        raise BundleRefused(f"{manifest.media.kind} bundles cannot be ingested yet")
    if isinstance(manifest.media, AudioMedia | YoutubeMedia):
        _check_audio(manifest.media)
    return manifest


def _check_audio(media: AudioMedia | YoutubeMedia) -> None:
    """The audio must be a format the transcriber and the player take, and captions WebVTT."""
    if PurePosixPath(media.audio).suffix.lower().lstrip(".") not in AUDIO_EXTENSIONS:
        raise BundleRefused(f"{media.audio} is not one of {', '.join(AUDIO_EXTENSIONS)}")
    if media.captions is not None and not media.captions.lower().endswith(".vtt"):
        raise BundleRefused(f"{media.captions} is not a WebVTT caption track")


def bundle_of(path: Path) -> Path | None:
    """The stored bundle `path` is inside, as `raw/<doc_id>.bundle/assets/<audio>` is."""
    for parent in path.parents:
        if parent.suffix == BUNDLE_SUFFIX and (parent / MANIFEST).is_file():
            return parent
    return None


def _copy_checked(source: Path, dest: Path) -> None:
    if not source.is_dir() or source.is_symlink():
        raise BundleRefused(f"{source.name} is not a directory")
    dest.mkdir(parents=True)
    totals = {"bytes": 0, "section_bytes": 0, "files": 0}
    pending = [(source, dest, PurePosixPath())]
    while pending:
        src_dir, dst_dir, rel_dir = pending.pop()
        with os.scandir(src_dir) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                child = _copy_entry(entry, dst_dir, rel_dir, totals)
                if child is not None:
                    pending.append(child)


def _copy_entry(
    entry: os.DirEntry, dst_dir: Path, rel_dir: PurePosixPath, totals: dict[str, int]
) -> tuple[Path, Path, PurePosixPath] | None:
    """Copy one listed entry; a directory is created and returned for the walk to enter."""
    rel = rel_dir / entry.name
    top_level = not rel_dir.parts
    if entry.is_symlink():
        raise BundleRefused(f"{rel} is a symbolic link")
    if entry.is_dir(follow_symlinks=False):
        if top_level and entry.name not in _TOP_LEVEL_DIRS:
            raise BundleRefused(f"{rel}/ is not part of a bundle")
        (dst_dir / entry.name).mkdir()
        return Path(entry.path), dst_dir / entry.name, rel
    if not entry.is_file(follow_symlinks=False):
        raise BundleRefused(f"{rel} is not a regular file")
    if top_level and entry.name != MANIFEST:
        raise BundleRefused(f"{rel} is not part of a bundle")
    _copy_file(Path(entry.path), dst_dir / entry.name, rel, totals)
    return None


def _copy_file(src: Path, dst: Path, rel: PurePosixPath, totals: dict[str, int]) -> None:
    totals["files"] += 1
    if totals["files"] > MAX_FILES:
        raise BundleRefused(f"the bundle holds more than {MAX_FILES:,} files")
    in_sections = rel.parts[0] == "sections"
    # A file swapped after the listing: a link is not followed, a pipe does not block the open.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    fd = os.open(src, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as fin, dst.open("wb") as fout:
        if not stat.S_ISREG(os.fstat(fin.fileno()).st_mode):
            raise BundleRefused(f"{rel} is not a regular file")
        size = 0
        while block := fin.read(_COPY_BLOCK):
            size += len(block)
            totals["bytes"] += len(block)
            if in_sections:
                totals["section_bytes"] += len(block)
            _check_ceilings(rel, size, totals, in_sections)
            fout.write(block)


def _check_ceilings(rel: PurePosixPath, size: int, totals: dict[str, int], in_sections: bool):
    if in_sections and size > MAX_SECTION_FILE_BYTES:
        raise BundleRefused(f"{rel} is larger than {_mib(MAX_SECTION_FILE_BYTES)}")
    if totals["section_bytes"] > MAX_SECTION_TEXT_BYTES:
        raise BundleRefused(f"the bundle's sections are larger than {_mib(MAX_SECTION_TEXT_BYTES)}")
    if totals["bytes"] > MAX_BUNDLE_BYTES:
        raise BundleRefused(f"the bundle is larger than {_mib(MAX_BUNDLE_BYTES)}")


def _mib(n: int) -> str:
    return f"{n // 1024**2:,} MiB"


def _utf8(raw: bytes, rel: str) -> str:
    """A connector decodes its source, so a bundle is UTF-8: I-68's first rule, never its guess."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BundleRefused(f"{rel} is not UTF-8 (byte {exc.start})") from exc


def _inside(root: Path, rel: str) -> Path:
    """`rel` as a regular file inside the bundle at `root`."""
    parts = PurePosixPath(rel).parts
    if PurePosixPath(rel).is_absolute() or ".." in parts or "." in parts:
        raise BundleRefused(f"{rel} leaves the bundle")
    path = root.joinpath(*parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise BundleRefused(f"{rel} leaves the bundle")
    if path.is_symlink() or not path.is_file():
        raise BundleRefused(f"{rel} is named in {MANIFEST} but the bundle does not contain it")
    return path


def read_manifest(root: Path) -> BundleManifest:
    """The manifest of the bundle at `root`, validated against the files beside it."""
    manifest = _load_manifest(root / MANIFEST)
    _check_files(root, manifest)
    return manifest


def _load_manifest(path: Path) -> BundleManifest:
    if path.is_symlink() or not path.is_file():
        raise BundleRefused(f"the bundle has no {MANIFEST}")
    try:
        data = json.loads(_utf8(path.read_bytes(), MANIFEST))
    except json.JSONDecodeError as exc:
        raise BundleRefused(f"{MANIFEST} is not JSON: {exc}") from exc
    version = data.get("bundle_version") if isinstance(data, dict) else None
    if version != BUNDLE_VERSION or isinstance(version, bool):
        raise BundleRefused(
            f"bundle_version {version!r} is not supported; this Luminary reads {BUNDLE_VERSION}"
        )
    try:
        return BundleManifest.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        more = f" (and {exc.error_count() - 1} more)" if exc.error_count() > 1 else ""
        raise BundleRefused(f"{MANIFEST}: {where}: {first['msg']}{more}") from exc


def _check_files(root: Path, manifest: BundleManifest) -> None:
    if len(manifest.sections) > MAX_SECTIONS:
        raise BundleRefused(f"the bundle has more than {MAX_SECTIONS:,} sections")
    if manifest.media.kind == "text" and not manifest.sections:
        raise BundleRefused("a text bundle has no sections")
    seen: set[str] = set()
    for section in manifest.sections:
        if section.id in seen:
            raise BundleRefused(f"section id {section.id!r} appears twice")
        seen.add(section.id)
        path = _inside(root, section.file)
        if path.suffix.lower() not in _SECTION_SUFFIXES:
            raise BundleRefused(f"{section.file} is neither HTML nor Markdown")
        _utf8(path.read_bytes(), section.file)
    media_files = [getattr(manifest.media, k, None) for k in ("audio", "captions")]
    for rel in (manifest.cover, *media_files):
        if rel is not None:
            _inside(root, rel)


def parse_bundle(root: Path) -> ParsedDocument:
    """A stored text bundle as the parser's document: each section file read as an EPUB
    chapter is, so a book gives the same sections whichever way it arrived."""
    from app.services.parser import (  # noqa: PLC0415 - the parser imports this module
        MIN_SECTION_CHARS,
        epub_chapter_sections,
    )

    manifest = read_manifest(root)
    if manifest.media.kind != "text":
        raise BundleRefused(f"{manifest.media.kind} bundles are transcribed, not parsed")
    sections: list[Section] = []
    for entry in manifest.sections:
        text = read_section(root, entry.file)
        if PurePosixPath(entry.file).suffix.lower() != ".md":
            sections.extend(epub_chapter_sections(text, entry.heading))
        elif len(text := text.strip()) >= MIN_SECTION_CHARS:
            sections.append(
                Section(heading=entry.heading, level=1, text=text, page_start=0, page_end=0)
            )
    if not sections:
        raise BundleRefused(f"no section of the bundle has {MIN_SECTION_CHARS} characters of text")
    raw_text = "\n\n".join(s.text for s in sections)
    return ParsedDocument(
        title=manifest.title,
        format="bundle",
        pages=0,
        word_count=len(raw_text.split()),
        sections=sections,
        raw_text=raw_text,
    )


def read_section(root: Path, rel: str) -> str:
    """A section file of the stored bundle at `root`, as text."""
    return _utf8(_inside(root, rel).read_bytes(), rel)


def bundle_images(root: Path) -> dict[str, tuple[str, bytes]]:
    """Every image under `assets/` but the cover, keyed by its path below `assets/`: the
    figures a book's chapters show, as an EPUB's image items are."""
    assets = root / "assets"
    cover = read_manifest(root).cover
    images: dict[str, tuple[str, bytes]] = {}
    for path in sorted(assets.rglob("*")) if assets.is_dir() else []:
        if path.relative_to(root).as_posix() == cover or path.is_symlink() or not path.is_file():
            continue
        mime, _ = mimetypes.guess_type(path.name)
        # Only images: a bundle's HTML served from the API origin would run as a page there.
        if mime and mime.startswith("image/"):
            images[path.relative_to(assets).as_posix()] = (mime, path.read_bytes())
    return images


def bundle_cover(root: Path) -> bytes | None:
    cover = read_manifest(root).cover
    return _inside(root, cover).read_bytes() if cover else None


def bundle_image(root: Path, rel: str) -> tuple[bytes, str] | None:
    """One image under `assets/`, by its path as a chapter wrote it or else by base name, as
    the EPUB asset route matches."""
    match = _asset_named(root / "assets", rel)
    mime = mimetypes.guess_type(match.name)[0] if match else None
    if match is None or not mime or not mime.startswith("image/"):
        return None
    return match.read_bytes(), mime


def _asset_named(assets: Path, rel: str) -> Path | None:
    if not assets.is_dir():
        return None
    files = [p for p in assets.rglob("*") if p.is_file() and not p.is_symlink()]
    name = PurePosixPath(rel).name.lower()
    exact = next((p for p in files if p.relative_to(assets).as_posix() == rel), None)
    return exact or next((p for p in files if p.name.lower() == name), None)
