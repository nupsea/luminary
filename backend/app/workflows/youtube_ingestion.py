"""Download a YouTube talk's audio, then hand it to the ingestion pipeline.

Runs as the document's ingestion job, so the request that created the document
returns at once and the download shows as the `downloading` stage.
"""

import logging
from pathlib import Path

from app.database import get_session_factory
from app.models import DocumentModel
from app.services import ingestion_progress
from app.services import youtube_downloader as _yt  # indirect: tests patch its functions
from app.services.captions import captions_path
from app.workflows.ingestion import run_ingestion

logger = logging.getLogger(__name__)


async def _fail(doc_id: str, message: str) -> None:
    async with get_session_factory()() as session:
        doc = await session.get(DocumentModel, doc_id)
        if doc:
            doc.stage = "error"
            doc.error_message = message
            await session.commit()


def _remove_partial_files(dest_stem: Path) -> None:
    for path in dest_stem.parent.glob(f"{dest_stem.name}.*"):
        path.unlink(missing_ok=True)


async def download_and_ingest(
    doc_id: str, url: str, dest_stem: Path, caption_track: str | None
) -> None:
    dest = dest_stem.with_suffix(_yt.AUDIO_SUFFIX)
    completed = False
    try:
        await _yt.download_audio(
            url,
            dest_stem,
            on_progress=lambda f: ingestion_progress.report(doc_id, "downloading", f),
        )
        if not dest.exists():
            await _fail(doc_id, "Audio download failed: the downloaded file was not found.")
            return
        if caption_track:
            await _yt.download_captions(url, captions_path(dest), caption_track)
        completed = True
    except Exception as exc:
        logger.exception("yt-dlp download failed")
        await _fail(doc_id, f"Audio download failed: {exc}")
        return
    finally:
        ingestion_progress.clear(doc_id)
        if not completed:
            _remove_partial_files(dest_stem)
    # run_ingestion records its own failures on the document.
    fmt = _yt.AUDIO_SUFFIX.lstrip(".")
    await run_ingestion(doc_id, str(dest), fmt, parsed_document=None)
