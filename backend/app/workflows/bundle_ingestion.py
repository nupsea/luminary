"""Hand a connector's bundle to the ingestion pipeline as a document's stored source."""

import asyncio
from pathlib import Path, PurePosixPath
from typing import Any

from app.database import get_session_factory
from app.exceptions import NotFound
from app.repos.document_repo import DocumentRepo
from app.schemas.source_bundle import AudioMedia, BundleManifest, YoutubeMedia
from app.services.connectors import MEDIA
from app.services.source_bundle import BUNDLE_SUFFIX, store_bundle
from app.services.transcript_vocabulary import vocabulary_from_metadata
from app.storage import library_root
from app.workflows.ingestion import run_ingestion


async def store_document_bundle(doc_id: str, source: Path) -> tuple[Path, str]:
    """Store the bundle at `source` as the document's source; (path to ingest, format).

    The document row must exist. Raises `BundleRefused` before anything is stored when the
    bundle fails a check; the caller records that on the document, as for a failed download.
    The document takes the manifest's title. Re-import and resume read the stored copy, so
    the connector never runs again.
    """
    async with get_session_factory()() as session:
        doc = await DocumentRepo(session).get(doc_id)
        if doc is None:
            raise NotFound(f"Document not found: {doc_id}")
        fmt = doc.format

    dest = library_root() / "raw" / f"{doc_id}{BUNDLE_SUFFIX}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest = await asyncio.to_thread(store_bundle, source, dest, media=frozenset(MEDIA))
    fields: dict[str, Any] = {"file_path": str(dest), "title": manifest.title, "format": fmt}
    if isinstance(manifest.media, AudioMedia | YoutubeMedia):
        fields |= _media_fields(dest, manifest, manifest.media)
    async with get_session_factory()() as session:
        await DocumentRepo(session).update_fields(doc_id, **fields)
        await session.commit()
    return Path(fields["file_path"]), fields["format"]


def _media_fields(
    dest: Path, manifest: BundleManifest, media: AudioMedia | YoutubeMedia
) -> dict[str, Any]:
    """An audio bundle is ingested as its audio file, as a downloaded talk is: the player,
    the transcriber and re-import read `file_path`, and captions come from `captions_for`."""
    audio = dest.joinpath(*PurePosixPath(media.audio).parts)
    fields: dict[str, Any] = {"file_path": str(audio), "format": audio.suffix.lower().lstrip(".")}
    if isinstance(media, YoutubeMedia):
        channel = manifest.authors[0] if manifest.authors else None
        # The shape of yt-dlp's metadata, which the built-in download primes Whisper from.
        meta = {
            "title": manifest.title,
            "uploader": channel,
            "tags": manifest.tags,
            "description": manifest.description,
            "chapters": [{"title": c} for c in manifest.chapters],
        }
        fields |= {
            "youtube_url": media.url,
            "video_title": manifest.title,
            "channel_name": channel,
            "transcript_vocabulary": vocabulary_from_metadata(meta) or None,
        }
    return fields


async def ingest_bundle(doc_id: str, source: Path) -> None:
    """Store the bundle at `source` as the document's source, then ingest it."""
    dest, fmt = await store_document_bundle(doc_id, source)
    # run_ingestion records its own failures on the document.
    await run_ingestion(doc_id, str(dest), fmt)
